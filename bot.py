import logging
import random
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
Application, CommandHandler, CallbackQueryHandler,
ContextTypes, MessageHandler, filters, ConversationHandler
)
from supabase import create_client

# ══════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════
TOKEN = os.getenv("TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)

# Estados para ConversationHandler
(
ESPERANDO_DIA, ESPERANDO_HORA,
ESPERANDO_PELICULA, ESPERANDO_ALBUM
) = range(4)


# ══════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════

def get_participantes(chat_id):
    return supabase.table("participantes").select("*").eq("chat_id", chat_id).execute().data

def get_juntada_activa(chat_id, estados):
    return supabase.table("juntadas").select("*").eq("chat_id", chat_id).in_("estado", estados).execute().data

def menu_keyboard():
    return InlineKeyboardMarkup([
    [InlineKeyboardButton("📅 Proponer fecha", callback_data="menu_proponer")],
    [InlineKeyboardButton("🗳 Ver votación de fecha", callback_data="menu_ver_fecha")],
    [InlineKeyboardButton("🎬 Agregar película", callback_data="menu_peli"),
        InlineKeyboardButton("🎵 Agregar álbum", callback_data="menu_album")],
    [InlineKeyboardButton("🎲 Sortear", callback_data="menu_sortear")],
    [InlineKeyboardButton("⭐ Puntuar", callback_data="menu_puntuar"),
        InlineKeyboardButton("📋 Historial", callback_data="menu_historial")],
])


# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
nombre = update.effective_user.first_name
telegram_id = update.effective_user.id
chat_id = update.effective_chat.id

existing = supabase.table("participantes").select("*")\
    .eq("telegram_id", telegram_id).eq("chat_id", chat_id).execute()

if not existing.data:
    supabase.table("participantes").insert({
        "telegram_id": telegram_id,
        "nombre": nombre,
        "chat_id": chat_id
    }).execute()

await update.message.reply_text(
    f"Hola {nombre}! 🎉 Quedaste registrado.\n\n"
    "Usá los comandos o el menú:",
    reply_markup=menu_keyboard()
)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("¿Qué querés hacer?", reply_markup=menu_keyboard())


# ══════════════════════════════════════════
#  MENÚ — botones principales
# ══════════════════════════════════════════

async def manejar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
data = query.data
chat_id = query.message.chat.id

if data == "menu_proponer":
    await query.message.reply_text(
        "Usá el comando /proponer para proponer una fecha y hora."
    )
elif data == "menu_ver_fecha":
    await _ver_votacion_fecha(query.message, chat_id)
elif data == "menu_peli":
    await query.message.reply_text(
        "Usá el comando /agregarpeli para agregar una película."
    )
elif data == "menu_album":
    await query.message.reply_text(
        "Usá el comando /agregaralbum para agregar un álbum."
    )
elif data == "menu_sortear":
    await _hacer_sorteo(query.message, context, chat_id)
elif data == "menu_puntuar":
    await _iniciar_puntaje(query.message, chat_id)
elif data == "menu_historial":
    await _mostrar_historial(query.message, chat_id)


# ══════════════════════════════════════════
#  PROPONER FECHA — /proponer
# ══════════════════════════════════════════

async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id

activa = get_juntada_activa(chat_id, ["votando_fecha"])
if activa:
    j = activa[0]
    await update.message.reply_text(
        f"⚠️ Ya hay una propuesta activa: {j.get('fecha_propuesta')} a las {j.get('hora_propuesta')}.\n"
        "Tiene que resolverse (aceptar o rechazar por unanimidad) antes de proponer otra."
    )
    return ConversationHandler.END

await update.message.reply_text("📅 ¿Qué día proponés? (ej: Sábado 15/02)")
return ESPERANDO_DIA

async def recibir_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
context.user_data["dia"] = update.message.text
await update.message.reply_text("🕐 ¿A qué hora? (ej: 20:00)")
return ESPERANDO_HORA

async def recibir_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
dia = context.user_data["dia"]
hora = update.message.text
nombre = update.effective_user.first_name
chat_id = update.effective_chat.id

# Crear o reutilizar juntada pendiente
pendiente = get_juntada_activa(chat_id, ["pendiente"])
if pendiente:
    juntada_id = pendiente[0]["id"]
else:
    nueva = supabase.table("juntadas").insert({"chat_id": chat_id, "estado": "pendiente"}).execute()
    juntada_id = nueva.data[0]["id"]

supabase.table("juntadas").update({
    "fecha_propuesta": dia,
    "hora_propuesta": hora,
    "estado": "votando_fecha"
}).eq("id", juntada_id).execute()

supabase.table("propuestas_horario").insert({
    "juntada_id": juntada_id,
    "propuesto_por": nombre,
    "fecha": dia,
    "hora": hora
}).execute()

# Limpiar votos anteriores para esta juntada
supabase.table("votos_horario").delete().eq("propuesta_id", juntada_id).execute()

keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Acepto", callback_data=f"voto_si_{juntada_id}"),
    InlineKeyboardButton("❌ Rechazo", callback_data=f"voto_no_{juntada_id}")
]])

participantes = get_participantes(chat_id)
await update.message.reply_text(
    f"📅 *Nueva propuesta de juntada*\n\n"
    f"📆 {dia} a las {hora}\n"
    f"Propuesto por: {nombre}\n\n"
    f"Necesita unanimidad ({len(participantes)} votos). ¡Voten!",
    parse_mode="Markdown",
    reply_markup=keyboard
)
return ConversationHandler.END


# ══════════════════════════════════════════
#  VER VOTACIÓN DE FECHA
# ══════════════════════════════════════════

async def ver_propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE):
await _ver_votacion_fecha(update.message, update.effective_chat.id)

async def _ver_votacion_fecha(message, chat_id):
activa = get_juntada_activa(chat_id, ["votando_fecha"])
if not activa:
    await message.reply_text("No hay ninguna propuesta de fecha activa ahora.")
    return

j = activa[0]
juntada_id = j["id"]
votos = supabase.table("votos_horario").select("*").eq("propuesta_id", juntada_id).execute().data
participantes = get_participantes(chat_id)
total_si = sum(1 for v in votos if v["voto"] == "si")
total_no = sum(1 for v in votos if v["voto"] == "no")

keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Acepto", callback_data=f"voto_si_{juntada_id}"),
    InlineKeyboardButton("❌ Rechazo", callback_data=f"voto_no_{juntada_id}")
]])

await message.reply_text(
    f"📅 *Propuesta activa:*\n\n"
    f"📆 {j.get('fecha_propuesta')} a las {j.get('hora_propuesta')}\n\n"
    f"✅ A favor: {total_si} | ❌ En contra: {total_no}\n"
    f"Faltan votar: {len(participantes) - len(votos)}",
    parse_mode="Markdown",
    reply_markup=keyboard
)

# ══════════════════════════════════════════
#  VOTAR FECHA
# ══════════════════════════════════════════

async def manejar_voto_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()

data = query.data
nombre = query.from_user.first_name
chat_id = query.message.chat.id

if data.startswith("voto_si_"):
    juntada_id = int(data.replace("voto_si_", ""))
    voto = "si"
else:
    juntada_id = int(data.replace("voto_no_", ""))
    voto = "no"

juntada_data = supabase.table("juntadas").select("*").eq("id", juntada_id).execute().data
if not juntada_data or juntada_data[0]["estado"] != "votando_fecha":
    await query.answer("Esta votación ya no está activa.", show_alert=True)
    return

j = juntada_data[0]

# Registrar o actualizar voto
existing = supabase.table("votos_horario").select("*")\
    .eq("propuesta_id", juntada_id).eq("participante", nombre).execute().data
if existing:
    supabase.table("votos_horario").update({"voto": voto})\
        .eq("propuesta_id", juntada_id).eq("participante", nombre).execute()
else:
    supabase.table("votos_horario").insert({
        "propuesta_id": juntada_id,
        "participante": nombre,
        "voto": voto
    }).execute()

participantes = get_participantes(chat_id)
votos = supabase.table("votos_horario").select("*").eq("propuesta_id", juntada_id).execute().data
total_si = sum(1 for v in votos if v["voto"] == "si")
total_no = sum(1 for v in votos if v["voto"] == "no")
total_part = len(participantes)

# Si hay al menos un rechazo → propuesta cancelada
if total_no > 0:
    supabase.table("juntadas").update({"estado": "pendiente"}).eq("id", juntada_id).execute()
    await query.edit_message_text(
        f"❌ *Propuesta rechazada*\n\n"
        f"{j['fecha_propuesta']} a las {j['hora_propuesta']}\n\n"
        f"✅ A favor: {total_si} | ❌ En contra: {total_no}\n\n"
        f"Ya pueden proponer una nueva fecha con /proponer",
        parse_mode="Markdown"
    )
    return

# Si todos votaron y todos dijeron sí → confirmada
if len(votos) >= total_part and total_si == total_part:
    supabase.table("juntadas").update({
        "estado": "fecha_confirmada",
        "fecha_elegida": j["fecha_propuesta"],
        "hora_elegida": j["hora_propuesta"]
    }).eq("id", juntada_id).execute()
    await query.edit_message_text(
        f"✅ *¡Fecha confirmada por unanimidad!*\n\n"
        f"📆 {j['fecha_propuesta']} a las {j['hora_propuesta']}\n\n"
        f"Ya pueden usar /sortear para elegir peli y álbum 🎲",
        parse_mode="Markdown"
    )
    return

# Todavía faltan votos
keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("✅ Acepto", callback_data=f"voto_si_{juntada_id}"),
    InlineKeyboardButton("❌ Rechazo", callback_data=f"voto_no_{juntada_id}")
]])
await query.edit_message_text(
    f"📅 *Propuesta:* {j['fecha_propuesta']} a las {j['hora_propuesta']}\n\n"
    f"✅ A favor: {total_si} | ❌ En contra: {total_no}\n"
    f"Faltan votar: {total_part - len(votos)}",
    parse_mode="Markdown",
    reply_markup=keyboard
)


# ══════════════════════════════════════════
#  AGREGAR PELÍCULA — /agregarpeli
# ══════════════════════════════════════════

async def agregar_peli(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("🎬 ¿Qué película querés agregar?")
return ESPERANDO_PELICULA

async def recibir_pelicula(update: Update, context: ContextTypes.DEFAULT_TYPE):
titulo = update.message.text
nombre = update.effective_user.first_name
supabase.table("peliculas").insert({
    "titulo": titulo,
    "agregada_por": nombre,
    "vista": False
}).execute()
await update.message.reply_text(f"🎬 Película agregada: *{titulo}*", parse_mode="Markdown")
return ConversationHandler.END


# ══════════════════════════════════════════
#  AGREGAR ÁLBUM — /agregaralbum
# ══════════════════════════════════════════

async def agregar_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("🎵 ¿Qué álbum querés agregar?\n(formato: Artista - Álbum)")
return ESPERANDO_ALBUM

async def recibir_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
texto = update.message.text
nombre = update.effective_user.first_name
partes = texto.split(" - ", 1)
artista = partes[0].strip() if len(partes) > 1 else "Desconocido"
titulo = partes[1].strip() if len(partes) > 1 else texto.strip()
supabase.table("albumes").insert({
    "titulo": titulo,
    "artista": artista,
    "agregado_por": nombre,
    "escuchado": False
}).execute()
await update.message.reply_text(f"🎵 Álbum agregado: *{artista} — {titulo}*", parse_mode="Markdown")
return ConversationHandler.END


# ══════════════════════════════════════════
#  SORTEAR — /sortear
# ══════════════════════════════════════════

async def sortear(update: Update, context: ContextTypes.DEFAULT_TYPE):
chat_id = update.effective_chat.id
await_hacer_sorteo(update.message, context, chat_id)

async def _hacer_sorteo(message, context, chat_id):
# Verificar que no haya un sorteo pendiente de votación
activo = get_juntada_activa(chat_id, ["votando_sorteo"])
if activo:
    j = activo[0]
    peli_id = j.get("pelicula_sorteada_id")
    album_id = j.get("album_sorteado_id")
    peli = supabase.table("peliculas").select("titulo").eq("id", peli_id).execute().data if peli_id else []
    album = supabase.table("albumes").select("titulo,artista").eq("id", album_id).execute().data if album_id else []
    peli_txt = peli[0]["titulo"] if peli else "—"
    album_txt = f"{album[0]['artista']} — {album[0]['titulo']}" if album else "—"
    await message.reply_text(
        f"⚠️ Ya hay un sorteo activo pendiente de votación:\n\n"
        f"🎬 {peli_txt}\n🎵 {album_txt}\n\n"
        f"Resolvé esa votación antes de sortear de nuevo."
    )
    return

pelis = supabase.table("peliculas").select("*").eq("vista", False).execute().data
albumes = supabase.table("albumes").select("*").eq("escuchado", False).execute().data

if not pelis and not albumes:
    await message.reply_text("No hay películas ni álbumes cargados aún.")
    return

juntada_data = get_juntada_activa(chat_id, ["fecha_confirmada", "pendiente"])
if not juntada_data:
    juntada_data = supabase.table("juntadas").insert({"chat_id": chat_id, "estado": "pendiente"}).execute().data

juntada_id = juntada_data[0]["id"]

peli = random.choice(pelis) if pelis else None
album = random.choice(albumes) if albumes else None

supabase.table("juntadas").update({
    "estado": "votando_sorteo",
    "pelicula_sorteada_id": peli["id"] if peli else None,
    "album_sorteado_id": album["id"] if album else None
}).eq("id", juntada_id).execute()

# Limpiar votos de sorteo anteriores
supabase.table("votos_sorteo").delete().eq("juntada_id", juntada_id).execute()

participantes = get_participantes(chat_id)
mensaje = "🎲 *Sorteo de la juntada*\n\n"
if peli:
    mensaje += f"🎬 Película: *{peli['titulo']}* (sugerida por {peli['agregada_por']})\n"
if album:
    mensaje += f"🎵 Álbum: *{album['artista']} — {album['titulo']}* (sugerido por {album['agregado_por']})\n"
mensaje += f"\nNecesita unanimidad ({len(participantes)} votos). ¡Voten!"

keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
    InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
]])

await message.reply_text(mensaje, parse_mode="Markdown", reply_markup=keyboard)

async def manejar_voto_sorteo(update: Update, context: ContextTypes.DEFAULT_TYPE):
try:
    query = update.callback_query
    await query.answer()

    data = query.data
    nombre = query.from_user.first_name
    chat_id = query.message.chat.id

    if data.startswith("sorteo_si_"):
        juntada_id = int(data.replace("sorteo_si_", ""))
        voto = "si"
    elif data.startswith("sorteo_no_"):
        juntada_id = int(data.replace("sorteo_no_", ""))
        voto = "no"
    else:
        return

    juntada_data = supabase.table("juntadas").select("*").eq("id", juntada_id).execute().data
    if not juntada_data or juntada_data[0]["estado"] != "votando_sorteo":
        await query.answer("Esta votación ya no está activa.", show_alert=True)
        return

    j = juntada_data[0]

    existing = supabase.table("votos_sorteo").select("*")\
        .eq("juntada_id", juntada_id).eq("participante", nombre).execute().data

    if existing:
        supabase.table("votos_sorteo").update({"voto": voto})\
            .eq("juntada_id", juntada_id).eq("participante", nombre).execute()
    else:
        supabase.table("votos_sorteo").insert({
            "juntada_id": juntada_id,
            "participante": nombre,
            "tipo": "sorteo",
            "voto": voto
        }).execute()

    participantes = get_participantes(chat_id)
    votos = supabase.table("votos_sorteo").select("*").eq("juntada_id", juntada_id).execute().data
    total_si = sum(1 for v in votos if v["voto"] == "si")
    total_no = sum(1 for v in votos if v["voto"] == "no")
    total_part = len(participantes)

    peli_id = j.get("pelicula_sorteada_id")
    album_id = j.get("album_sorteado_id")

    peli = supabase.table("peliculas").select("titulo").eq("id", peli_id).execute().data if peli_id else []
    album = supabase.table("albumes").select("titulo,artista").eq("id", album_id).execute().data if album_id else []

    peli_txt = peli[0]["titulo"] if peli else "—"
    album_txt = f"{album[0]['artista']} — {album[0]['titulo']}" if album else "—"

    if total_no > 0:
        supabase.table("juntadas").update({"estado": "fecha_confirmada"}).eq("id", juntada_id).execute()
        await query.edit_message_text(
            f"🔄 Sorteo rechazado. Pueden hacer /sortear para un nuevo sorteo.\n\n"
            f"✅ A favor: {total_si} | ❌ En contra: {total_no}"
        )
        return

    if len(votos) >= total_part and total_si == total_part:
        supabase.table("juntadas").update({"estado": "sorteo_confirmado"}).eq("id", juntada_id).execute()
        await query.edit_message_text(
            f"✅ Sorteo confirmado por unanimidad!\n\n"
            f"🎬 {peli_txt}\n"
            f"🎵 {album_txt}\n\n"
            f"¡Que disfruten la juntada! 🎉\n"
            f"Al terminar usen /puntuar"
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
        InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
    ]])

    await query.edit_message_text(
        f"🎲 Sorteo activo:\n\n"
        f"🎬 {peli_txt}\n"
        f"🎵 {album_txt}\n\n"
        f"✅ A favor: {total_si} | ❌ En contra: {total_no}\n"
        f"Faltan votar: {total_part - len(votos)}",
        reply_markup=keyboard
    )

except Exception as e:
    logging.exception("Error en manejar_voto_sorteo")
    await query.message.reply_text(f"ERROR voto sorteo: {e}")

    participantes = get_participantes(chat_id)
    votos = supabase.table("votos_sorteo").select("*").eq("juntada_id", juntada_id).execute().data
    total_si = sum(1 for v in votos if v["voto"] == "si")
    total_no = sum(1 for v in votos if v["voto"] == "no")
    total_part = len(participantes)

    peli_id = j.get("pelicula_sorteada_id")
    album_id = j.get("album_sorteado_id")
    peli = supabase.table("peliculas").select("titulo").eq("id", peli_id).execute().data if peli_id else []
    album = supabase.table("albumes").select("titulo,artista").eq("id", album_id).execute().data if album_id else []

    peli_txt = peli[0]["titulo"] if peli else "—"
    album_txt = f"{album[0]['artista']} — {album[0]['titulo']}" if album else "—"

    if total_no > 0:
        supabase.table("juntadas").update({"estado": "fecha_confirmada"}).eq("id", juntada_id).execute()
        await query.edit_message_text(
            f"🔄 Sorteo rechazado. Pueden hacer /sortear para un nuevo sorteo.\n\n"
            f"✅ A favor: {total_si} | ❌ En contra: {total_no}"
        )
        return

    if len(votos) >= total_part and total_si == total_part:
        supabase.table("juntadas").update({"estado": "sorteo_confirmado"}).eq("id", juntada_id).execute()
        await query.edit_message_text(
            f"✅ Sorteo confirmado por unanimidad!\n\n"
            f"🎬 {peli_txt}\n"
            f"🎵 {album_txt}\n\n"
            f"¡Que disfruten la juntada! 🎉\n"
            f"Al terminar usen /puntuar"
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
        InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
    ]])

    await query.edit_message_text(
        f"🎲 Sorteo activo:\n\n"
        f"🎬 {peli_txt}\n"
        f"🎵 {album_txt}\n\n"
        f"✅ A favor: {total_si} | ❌ En contra: {total_no}\n"
        f"Faltan votar: {total_part - len(votos)}",
        reply_markup=keyboard
    )

except Exception as e:
    logging.exception("Error en manejar_voto_sorteo")
    await query.message.reply_text(f"ERROR voto sorteo: {e}")

# ══════════════════════════════════════════
#  PUNTUAR — /puntuar
# ══════════════════════════════════════════

async def puntuar(update: Update, context: ContextTypes.DEFAULT_TYPE):
await _iniciar_puntaje(update.message, update.effective_chat.id)

async def _iniciar_puntaje(message, chat_id):
# Solo se puede puntuar si hay un sorteo confirmado
confirmado = get_juntada_activa(chat_id, ["sorteo_confirmado"])
if not confirmado:
    await message.reply_text(
        "⚠️ No hay nada para puntuar todavía.\n"
        "El sorteo tiene que estar confirmado por unanimidad primero."
    )
    return

j = confirmado[0]
peli_id = j.get("pelicula_sorteada_id")
album_id = j.get("album_sorteado_id")

botones = []
if peli_id:
    peli = supabase.table("peliculas").select("titulo").eq("id", peli_id).execute().data
    if peli:
        botones.append([InlineKeyboardButton(
            f"🎬 Puntuar: {peli[0]['titulo']}",
            callback_data=f"puntuar_peli_{peli_id}_{j['id']}"
        )])
if album_id:
    album = supabase.table("albumes").select("titulo,artista").eq("id", album_id).execute().data
    if album:
        botones.append([InlineKeyboardButton(
            f"🎵 Puntuar: {album[0]['artista']} — {album[0]['titulo']}",
            callback_data=f"puntuar_album_{album_id}_{j['id']}"
        )])

if not botones:
    await message.reply_text("No encontré items para puntuar.")
    return

await message.reply_text(
    "⭐ ¿Qué querés puntuar?",
    reply_markup=InlineKeyboardMarkup(botones)
)

async def manejar_puntaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
data = query.data
nombre = query.from_user.first_name

# puntuar_peli_{peli_id}_{juntada_id}  o  puntuar_album_{album_id}_{juntada_id}
if data.startswith("puntuar_peli_"):
    partes = data.replace("puntuar_peli_", "").split("_")
    item_id = int(partes[0])
    juntada_id = int(partes[1])
    tipo = "pelicula"
elif data.startswith("puntuar_album_"):
    partes = data.replace("puntuar_album_", "").split("_")
    item_id = int(partes[0])
    juntada_id = int(partes[1])
    tipo = "album"
elif data.startswith("estrella_"):
    # estrella_{tipo}_{item_id}_{juntada_id}_{puntaje}
    partes = data.replace("estrella_", "").split("_")
    tipo = partes[0]
    item_id = int(partes[1])
    juntada_id = int(partes[2])
    puntaje = int(partes[3])

# Guardar en puntuaciones
existing = supabase.table("puntuaciones").select("*")\
.eq("item_id", item_id)\
.eq("tipo", tipo)\
.eq("participante", nombre)\
.execute().data

if existing:
intentos = existing[0].get("intentos", 1)

if intentos >= 2:
    await query.answer(
        "Ya agotaste tus 2 intentos de puntuación para este item.",
        show_alert=True
    )
    return

supabase.table("puntuaciones").update({
    "puntaje": puntaje,
    "intentos": intentos + 1
})\
.eq("item_id", item_id)\
.eq("tipo", tipo)\
.eq("participante", nombre)\
.execute()

else:
supabase.table("puntuaciones").insert({
    "participante": nombre,
    "tipo": tipo,
    "item_id": item_id,
    "puntaje": puntaje,
    "intentos": 1
}).execute()



if tipo == "pelicula":
supabase.table("peliculas").update({"vista": True}).eq("id", item_id).execute()
else:
supabase.table("albumes").update({"escuchado": True}).eq("id", item_id).execute()

await query.edit_message_text(
f"{'🎬' if tipo == 'pelicula' else '🎵'} Puntaje registrado: {'⭐' * puntaje} ({puntaje}/5)\n"
f"Gracias {nombre}! Podés puntuar el otro item con /puntuar"
)
return

# Mostrar estrellas
estrellas = [[
    InlineKeyboardButton(f"{'⭐' * i} {i}", callback_data=f"estrella_{tipo}_{item_id}_{juntada_id}_{i}")
    for i in range(1, 6)
]]
tipo_txt = "película" if tipo == "pelicula" else "álbum"
await query.edit_message_text(
    f"¿Cuántas estrellas le das a {'la' if tipo == 'pelicula' else 'el'} {tipo_txt}?",
    reply_markup=InlineKeyboardMarkup(estrellas)
)


# ══════════════════════════════════════════
#  HISTORIAL — /historial
# ══════════════════════════════════════════

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
await _mostrar_historial(update.message, update.effective_chat.id)

async def _mostrar_historial(message, chat_id):
pelis = supabase.table("peliculas").select("*").eq("vista", True).execute().data
albumes = supabase.table("albumes").select("*").eq("escuchado", True).execute().data

if not pelis and not albumes:
    await message.reply_text("📋 Todavía no hay nada en el historial.")
    return

mensaje = "📋 *Historial de juntadas*\n\n"

if pelis:
    mensaje += "🎬 *Películas vistas:*\n"
    for p in pelis:
        punts = supabase.table("puntuaciones").select("*")\
            .eq("item_id", p["id"]).eq("tipo", "pelicula").execute().data
        if punts:
            promedio = sum(x["puntaje"] for x in punts) / len(punts)
            detalle = " | ".join([f"{x['participante']}: {x['puntaje']}⭐" for x in punts])
            mensaje += f"  • *{p['titulo']}*\n    Promedio: {promedio:.1f}⭐\n    {detalle}\n"
        else:
            mensaje += f"  • *{p['titulo']}* — sin puntajes\n"

if albumes:
    mensaje += "\n🎵 *Álbumes escuchados:*\n"
    for a in albumes:
        punts = supabase.table("puntuaciones").select("*")\
            .eq("item_id", a["id"]).eq("tipo", "album").execute().data
        if punts:
            promedio = sum(x["puntaje"] for x in punts) / len(punts)
            detalle = " | ".join([f"{x['participante']}: {x['puntaje']}⭐" for x in punts])
            mensaje += f"  • *{a['artista']} — {a['titulo']}*\n    Promedio: {promedio:.1f}⭐\n    {detalle}\n"
        else:
            mensaje += f"  • *{a['artista']} — {a['titulo']}* — sin puntajes\n"

await message.reply_text(mensaje, parse_mode="Markdown")


# ══════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════

def main():
app = Application.builder().token(TOKEN).build()

conv_proponer = ConversationHandler(
    entry_points=[CommandHandler("proponer", proponer)],
    states={
        ESPERANDO_DIA:  [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_dia)],
        ESPERANDO_HORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_hora)],
    },
    fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)]
)

conv_peli = ConversationHandler(
    entry_points=[CommandHandler("agregarpeli", agregar_peli)],
    states={
        ESPERANDO_PELICULA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_pelicula)]
    },
    fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)]
)

conv_album = ConversationHandler(
    entry_points=[CommandHandler("agregaralbum", agregar_album)],
    states={
        ESPERANDO_ALBUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_album)]
    },
    fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)]
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("menu", menu))
app.add_handler(CommandHandler("verpropuestas", ver_propuestas))
app.add_handler(CommandHandler("sortear", sortear))
app.add_handler(CommandHandler("puntuar", puntuar))
app.add_handler(CommandHandler("historial", historial))

app.add_handler(conv_proponer)
app.add_handler(conv_peli)
app.add_handler(conv_album)

app.add_handler(CallbackQueryHandler(manejar_menu,         pattern="^menu_"))
app.add_handler(CallbackQueryHandler(manejar_voto_horario, pattern="^voto_"))
app.add_handler(CallbackQueryHandler(manejar_voto_sorteo,  pattern="^sorteo_"))
app.add_handler(CallbackQueryHandler(manejar_puntaje,      pattern="^(puntuar_|estrella_)"))

print("✅ Bot corriendo...")
app.run_polling()

if __name__ == "__main__":
main()
