import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from supabase import create_client

# ══════════════════════════════════════════
#  CONFIGURACIÓN - COMPLETÁ ESTOS DATOS
# ══════════════════════════════════════════
import os

TOKEN = os.getenv("8750613819:AAHA6pjgTRZ4mSLjrmZnOpE5-xhyxUSPNCc")
SUPABASE_URL = os.getenv("https://nizgneczrwohfkhgrprw.supabase.co")
SUPABASE_KEY = os.getenv("sb_publishable_J5SUxL_r3JDgaiYfxq6sLQ_Gcbout8-")

# ══════════════════════════════════════════
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)

ESPERANDO_DIA, ESPERANDO_HORA, ESPERANDO_PELICULA, ESPERANDO_ALBUM, ESPERANDO_PUNTAJE_PELI, ESPERANDO_PUNTAJE_ALBUM = range(6)

# ── INICIO ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name
    telegram_id = update.effective_user.id
    existing = supabase.table("participantes").select("*").eq("telegram_id", telegram_id).execute()
    if not existing.data:
        supabase.table("participantes").insert({"telegram_id": telegram_id, "nombre": nombre}).execute()
    await update.message.reply_text(
        f"Hola {nombre}! 🎉 Bienvenido al bot de juntadas.\n\n"
        "Comandos disponibles:\n"
        "/proponer - Proponer día y hora\n"
        "/verpropuestas - Ver propuestas y votar\n"
        "/agregarpeli - Agregar película\n"
        "/agregaralbum - Agregar álbum\n"
        "/sortear - Sortear peli y álbum\n"
        "/puntuar - Puntuar lo que vimos\n"
        "/historial - Ver historial"
    )

# ── PROPONER DÍA ──
async def proponer(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    juntada = supabase.table("juntadas").select("*").eq("estado", "pendiente").execute()
    if not juntada.data:
        juntada = supabase.table("juntadas").insert({"estado": "pendiente"}).execute()
        juntada_id = juntada.data[0]["id"]
    else:
        juntada_id = juntada.data[0]["id"]
    supabase.table("propuestas_horario").insert({
        "juntada_id": juntada_id,
        "propuesto_por": nombre,
        "fecha": dia,
        "hora": hora
    }).execute()
    await update.message.reply_text(f"✅ Propuesta cargada: {dia} a las {hora}")
    return ConversationHandler.END

# ── VER PROPUESTAS Y VOTAR ──
async def ver_propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    juntada = supabase.table("juntadas").select("*").eq("estado", "pendiente").execute()
    if not juntada.data:
        await update.message.reply_text("No hay juntada pendiente. Usá /proponer para crear una.")
        return
    juntada_id = juntada.data[0]["id"]
    propuestas = supabase.table("propuestas_horario").select("*").eq("juntada_id", juntada_id).execute()
    if not propuestas.data:
        await update.message.reply_text("No hay propuestas todavía. Usá /proponer.")
        return
    keyboard = []
    for p in propuestas.data:
        texto = f"{p['fecha']} {p['hora']} (por {p['propuesto_por']})"
        keyboard.append([
            InlineKeyboardButton(f"✅ {texto}", callback_data=f"voto_si_{p['id']}"),
            InlineKeyboardButton(f"❌", callback_data=f"voto_no_{p['id']}")
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Propuestas de horario — votá:", reply_markup=reply_markup)

async def manejar_voto_horario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    nombre = query.from_user.first_name
    if data.startswith("voto_si_"):
        propuesta_id = int(data.replace("voto_si_", ""))
        voto = "si"
    else:
        propuesta_id = int(data.replace("voto_no_", ""))
        voto = "no"
    existing = supabase.table("votos_horario").select("*").eq("propuesta_id", propuesta_id).eq("participante", nombre).execute()
    if existing.data:
        supabase.table("votos_horario").update({"voto": voto}).eq("propuesta_id", propuesta_id).eq("participante", nombre).execute()
    else:
        supabase.table("votos_horario").insert({"propuesta_id": propuesta_id, "participante": nombre, "voto": voto}).execute()
    emoji = "✅" if voto == "si" else "❌"
    await query.edit_message_text(f"Voto registrado {emoji} — {nombre}")

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