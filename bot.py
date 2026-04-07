import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from supabase import create_client

# ══════════════════════════════════════════
#  CONFIGURACIÓN - COMPLETÁ ESTOS DATOS
# ══════════════════════════════════════════
import os

TOKEN = os.getenv("TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ══════════════════════════════════════════
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)

ESPERANDO_DIA, ESPERANDO_HORA, ESPERANDO_PELICULA, ESPERANDO_ALBUM, ESPERANDO_PUNTAJE_PELI, ESPERANDO_PUNTAJE_ALBUM = range(6)

# ── INICIO ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name
    telegram_id = update.effective_user.id
    chat_id = update.effective_chat.id

    existing = supabase.table("participantes").select("*").eq("telegram_id", telegram_id).eq("chat_id", chat_id).execute()

    if not existing.data:
        supabase.table("participantes").insert({
            "telegram_id": telegram_id,
            "nombre": nombre,
            "chat_id": chat_id
        }).execute()

    keyboard = [
        [InlineKeyboardButton("📅 Proponer fecha", callback_data="menu_proponer")],
        [InlineKeyboardButton("🗳 Ver votación activa", callback_data="menu_ver_propuesta")],
        [InlineKeyboardButton("🎬 Agregar película", callback_data="menu_agregar_peli")],
        [InlineKeyboardButton("🎵 Agregar álbum", callback_data="menu_agregar_album")],
        [InlineKeyboardButton("🎲 Sortear", callback_data="menu_sortear")],
        [InlineKeyboardButton("📋 Historial", callback_data="menu_historial")]
    ]

    await update.message.reply_text(
        f"Hola {nombre}! 🎉 Ya quedaste registrado en este grupo.\n\nElegí una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ── PROPONER DÍA ──
async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    juntada = supabase.table("juntadas").select("*").eq("chat_id", chat_id).in_("estado", ["esperando_fecha", "votando_fecha"]).execute()

    if juntada.data:
        await update.message.reply_text("⚠️ Ya hay una propuesta de fecha en curso. Esperá a que se resuelva.")
        return ConversationHandler.END

    # crear nueva juntada
    nueva = supabase.table("juntadas").insert({
        "chat_id": chat_id,
        "estado": "esperando_fecha"
    }).execute()

    context.user_data["juntada_id"] = nueva.data[0]["id"]

    await update.message.reply_text("¿Qué día proponés? (ej: Sábado 15/02)")
    return ESPERANDO_DIA

async def recibir_dia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["dia"] = update.message.text
    await update.message.reply_text("¿A qué hora? (ej: 20:00)")
    return ESPERANDO_HORA

async def recibir_hora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dia = context.user_data["dia"]
    hora = update.message.text
    nombre = update.effective_user.first_name
    chat_id = update.effective_chat.id

    juntada = supabase.table("juntadas").select("*").eq("chat_id", chat_id).eq("estado", "esperando_fecha").execute()

    if not juntada.data:
        await update.message.reply_text("⚠️ No encontré una juntada activa para esta propuesta.")
        return ConversationHandler.END

    juntada_id = juntada.data[0]["id"]

    supabase.table("propuestas_horario").insert({
        "juntada_id": juntada_id,
        "propuesto_por": nombre,
        "fecha": dia,
        "hora": hora
    }).execute()

    supabase.table("juntadas").update({
        "fecha_propuesta": dia,
        "hora_propuesta": hora,
        "estado": "votando_fecha"
    }).eq("id", juntada_id).execute()

    keyboard = [[
        InlineKeyboardButton("✅ Acepto", callback_data=f"voto_si_{juntada_id}"),
        InlineKeyboardButton("❌ Rechazo", callback_data=f"voto_no_{juntada_id}")
    ]]

    await update.message.reply_text(
        f"📅 Nueva propuesta de juntada:\n\n{dia} a las {hora}\n\nVoten todos. Tiene que haber unanimidad.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return ConversationHandler.END

# ── VER PROPUESTAS Y VOTAR ──
async def ver_propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    juntada = supabase.table("juntadas").select("*").eq("chat_id", chat_id).eq("estado", "votando_fecha").execute()

    if not juntada.data:
        await update.message.reply_text("No hay una propuesta de fecha activa en este momento.")
        return

    juntada_actual = juntada.data[0]
    juntada_id = juntada_actual["id"]
    fecha = juntada_actual.get("fecha_propuesta")
    hora = juntada_actual.get("hora_propuesta")

    keyboard = [[
        InlineKeyboardButton("✅ Acepto", callback_data=f"voto_si_{juntada_id}"),
        InlineKeyboardButton("❌ Rechazo", callback_data=f"voto_no_{juntada_id}")
    ]]

    await update.message.reply_text(
        f"📅 Propuesta activa:\n\n{fecha} a las {hora}\n\nVoten todos. Tiene que haber unanimidad.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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

    propuesta = supabase.table("juntadas").select("*").eq("id", juntada_id).eq("chat_id", chat_id).execute()

    if not propuesta.data:
        await query.edit_message_text("⚠️ No encontré la juntada activa.")
        return

    estado_actual = propuesta.data[0]["estado"]

    if estado_actual != "votando_fecha":
        await query.edit_message_text("⚠️ Esta votación ya no está activa.")
        return

    existing = supabase.table("votos_horario").select("*").eq("propuesta_id", juntada_id).eq("participante", nombre).execute()

    if existing.data:
        supabase.table("votos_horario").update({"voto": voto}).eq("propuesta_id", juntada_id).eq("participante", nombre).execute()
    else:
        supabase.table("votos_horario").insert({
            "propuesta_id": juntada_id,
            "participante": nombre,
            "voto": voto
        }).execute()

    participantes = supabase.table("participantes").select("*").eq("chat_id", chat_id).execute()
    votos = supabase.table("votos_horario").select("*").eq("propuesta_id", juntada_id).execute()

    total_participantes = len(participantes.data)
    total_votos = len(votos.data)
    total_no = len([v for v in votos.data if v["voto"] == "no"])
    total_si = len([v for v in votos.data if v["voto"] == "si"])

    if total_no > 0:
        supabase.table("juntadas").update({"estado": "esperando_fecha"}).eq("id", juntada_id).execute()
        await query.edit_message_text(
            f"❌ La propuesta fue rechazada.\n\n"
            f"Sí: {total_si} | No: {total_no}\n\n"
            f"Ya se puede proponer una nueva fecha con /proponer"
        )
        return

    if total_votos == total_participantes and total_si == total_participantes:
        supabase.table("juntadas").update({
            "fecha_confirmada": propuesta.data[0]["fecha_propuesta"],
            "hora_confirmada": propuesta.data[0]["hora_propuesta"],
            "estado": "fecha_confirmada"
        }).eq("id", juntada_id).execute()

        await query.edit_message_text(
            f"✅ Fecha confirmada por unanimidad:\n\n"
            f"{propuesta.data[0]['fecha_propuesta']} a las {propuesta.data[0]['hora_propuesta']}"
        )
        return

    await query.edit_message_text(
        f"🗳️ Voto registrado de {nombre}\n\n"
        f"Sí: {total_si} | No: {total_no}\n"
        f"Faltan votar: {total_participantes - total_votos}"
    )

# ── AGREGAR PELÍCULA ──
async def agregar_peli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué película querés agregar?")
    return ESPERANDO_PELICULA

async def recibir_pelicula(update: Update, context: ContextTypes.DEFAULT_TYPE):
    titulo = update.message.text
    nombre = update.effective_user.first_name
    supabase.table("peliculas").insert({"titulo": titulo, "agregada_por": nombre, "vista": False}).execute()
    await update.message.reply_text(f"🎬 Película agregada: {titulo}")
    return ConversationHandler.END

# ── AGREGAR ÁLBUM ──
async def agregar_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué álbum querés agregar? (formato: Artista - Álbum)")
    return ESPERANDO_ALBUM

async def recibir_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    nombre = update.effective_user.first_name
    partes = texto.split(" - ", 1)
    artista = partes[0] if len(partes) > 1 else "Desconocido"
    titulo = partes[1] if len(partes) > 1 else texto
    supabase.table("albumes").insert({"titulo": titulo, "artista": artista, "agregado_por": nombre, "escuchado": False}).execute()
    await update.message.reply_text(f"🎵 Álbum agregado: {artista} - {titulo}")
    return ConversationHandler.END

# ── SORTEAR ──
async def sortear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pelis = supabase.table("peliculas").select("*").eq("vista", False).execute()
    albumes = supabase.table("albumes").select("*").eq("escuchado", False).execute()
    mensaje = "🎲 *Sorteo de la juntada:*\n\n"
    if pelis.data:
        peli = random.choice(pelis.data)
        mensaje += f"🎬 Película: *{peli['titulo']}* (sugerida por {peli['agregada_por']})\n"
        context.bot_data["ultima_peli_id"] = peli["id"]
    else:
        mensaje += "🎬 No hay películas cargadas.\n"
    if albumes.data:
        album = random.choice(albumes.data)
        mensaje += f"🎵 Álbum: *{album['artista']} - {album['titulo']}* (sugerido por {album['agregado_por']})\n"
        context.bot_data["ultimo_album_id"] = album["id"]
    else:
        mensaje += "🎵 No hay álbumes cargados.\n"
    keyboard = [[
        InlineKeyboardButton("👍 Me copa", callback_data="sorteo_si"),
        InlineKeyboardButton("👎 Otro", callback_data="sorteo_no")
    ]]
    await update.message.reply_text(mensaje, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def manejar_voto_sorteo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "sorteo_no":
        await query.edit_message_text("Usá /sortear de nuevo para obtener otra combinación.")
    else:
        await query.edit_message_text("¡Genial! 🎉 Que disfruten la juntada. Al terminar usen /puntuar.")

# ── PUNTUAR ──
async def puntuar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⭐ 1", callback_data="punt_peli_1"),
         InlineKeyboardButton("⭐⭐ 2", callback_data="punt_peli_2"),
         InlineKeyboardButton("⭐⭐⭐ 3", callback_data="punt_peli_3"),
         InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data="punt_peli_4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data="punt_peli_5")]
    ]
    await update.message.reply_text("¿Cuánto le das a la película?", reply_markup=InlineKeyboardMarkup(keyboard))

async def manejar_puntaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("punt_peli_"):
        puntaje = int(data.replace("punt_peli_", ""))
        peli_id = context.bot_data.get("ultima_peli_id")
        if peli_id:
            peli = supabase.table("peliculas").select("*").eq("id", peli_id).execute()
            puntaje_actual = peli.data[0].get("puntaje") or 0
            nuevo_puntaje = (puntaje_actual + puntaje) / 2 if puntaje_actual else puntaje
            supabase.table("peliculas").update({"puntaje": nuevo_puntaje, "vista": True}).eq("id", peli_id).execute()
        keyboard = [
            [InlineKeyboardButton("⭐ 1", callback_data="punt_album_1"),
             InlineKeyboardButton("⭐⭐ 2", callback_data="punt_album_2"),
             InlineKeyboardButton("⭐⭐⭐ 3", callback_data="punt_album_3"),
             InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data="punt_album_4"),
             InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data="punt_album_5")]
        ]
        await query.edit_message_text(f"Película: {puntaje}⭐ registrado!\n\n¿Y el álbum?", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("punt_album_"):
        puntaje = int(data.replace("punt_album_", ""))
        album_id = context.bot_data.get("ultimo_album_id")
        if album_id:
            album = supabase.table("albumes").select("*").eq("id", album_id).execute()
            puntaje_actual = album.data[0].get("puntaje") or 0
            nuevo_puntaje = (puntaje_actual + puntaje) / 2 if puntaje_actual else puntaje
            supabase.table("albumes").update({"puntaje": nuevo_puntaje, "escuchado": True}).eq("id", album_id).execute()
        await query.edit_message_text(f"Álbum: {puntaje}⭐ registrado! Gracias 🎉")

# ── HISTORIAL ──
async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pelis = supabase.table("peliculas").select("*").eq("vista", True).execute()
    albumes = supabase.table("albumes").select("*").eq("escuchado", True).execute()
    mensaje = "📋 *Historial:*\n\n"
    if pelis.data:
        mensaje += "🎬 *Películas vistas:*\n"
        for p in pelis.data:
            punt = f"{p['puntaje']:.1f}⭐" if p.get('puntaje') else "sin puntaje"
            mensaje += f"  • {p['titulo']} — {punt}\n"
    else:
        mensaje += "🎬 Sin películas vistas aún.\n"
    mensaje += "\n"
    if albumes.data:
        mensaje += "🎵 *Álbumes escuchados:*\n"
        for a in albumes.data:
            punt = f"{a['puntaje']:.1f}⭐" if a.get('puntaje') else "sin puntaje"
            mensaje += f"  • {a['artista']} - {a['titulo']} — {punt}\n"
    else:
        mensaje += "🎵 Sin álbumes escuchados aún.\n"
    await update.message.reply_text(mensaje, parse_mode="Markdown")

# ── MAIN ──
def main():
    app = Application.builder().token(TOKEN).build()
    conv_proponer = ConversationHandler(
        entry_points=[CommandHandler("proponer", proponer)],
        states={
            ESPERANDO_DIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_dia)],
            ESPERANDO_HORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_hora)],
        },
        fallbacks=[]
    )
    conv_peli = ConversationHandler(
        entry_points=[CommandHandler("agregarpeli", agregar_peli)],
        states={ESPERANDO_PELICULA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_pelicula)]},
        fallbacks=[]
    )
    conv_album = ConversationHandler(
        entry_points=[CommandHandler("agregaralbum", agregar_album)],
        states={ESPERANDO_ALBUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_album)]},
        fallbacks=[]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_proponer)
    app.add_handler(conv_peli)
    app.add_handler(conv_album)
    app.add_handler(CommandHandler("verpropuestas", ver_propuestas))
    app.add_handler(CommandHandler("sortear", sortear))
    app.add_handler(CommandHandler("puntuar", puntuar))
    app.add_handler(CommandHandler("historial", historial))
    app.add_handler(CallbackQueryHandler(manejar_voto_horario, pattern="^voto_"))
    app.add_handler(CallbackQueryHandler(manejar_voto_sorteo, pattern="^sorteo_"))
    app.add_handler(CallbackQueryHandler(manejar_puntaje, pattern="^punt_"))
    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()