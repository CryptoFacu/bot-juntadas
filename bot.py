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

TOKEN = os.getenv("TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)

(ESPERANDO_DIA, ESPERANDO_HORA, ESPERANDO_PELICULA, ESPERANDO_ALBUM) = range(4)

# ================= HELPERS =================

def get_participantes(chat_id):
    return supabase.table("participantes").select("*").eq("chat_id", chat_id).execute().data

def get_juntada_activa(chat_id, estados):
    return supabase.table("juntadas")\
        .select("*")\
        .eq("chat_id", chat_id)\
        .in_("estado", estados)\
        .order("id", desc=True)\
        .limit(1)\
        .execute().data

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

# ================= START =================

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
        f"Hola {nombre}! 🎉 Quedaste registrado.",
        reply_markup=menu_keyboard()
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué querés hacer?", reply_markup=menu_keyboard())

# ================= MENU =================

async def manejar_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat.id

    if data == "menu_sortear":
        await _hacer_sorteo(query.message, context, chat_id)

# ================= SORTEO =================

async def sortear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _hacer_sorteo(update.message, context, update.effective_chat.id)

async def _hacer_sorteo(message, context, chat_id):
    pelis = supabase.table("peliculas").select("*").eq("vista", False).execute().data
    albumes = supabase.table("albumes").select("*").eq("escuchado", False).execute().data

    juntada_data = get_juntada_activa(chat_id, ["fecha_confirmada", "pendiente"])
    if not juntada_data:
        nueva = supabase.table("juntadas").insert({"chat_id": chat_id, "estado": "pendiente"}).execute()
        juntada_id = nueva.data[0]["id"]
    else:
        juntada_id = juntada_data[0]["id"]

    peli = random.choice(pelis) if pelis else None
    album = random.choice(albumes) if albumes else None

    supabase.table("juntadas").update({
        "estado": "votando_sorteo",
        "pelicula_sorteada_id": peli["id"] if peli else None,
        "album_sorteado_id": album["id"] if album else None
    }).eq("id", juntada_id).execute()

    supabase.table("votos_sorteo").delete().eq("juntada_id", juntada_id).execute()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
        InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
    ]])

    await message.reply_text("🎲 Sorteo listo. ¡Voten!", reply_markup=keyboard)

# ================= FIX PRINCIPAL =================

async def manejar_voto_sorteo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        data = query.data
        telegram_id = query.from_user.id
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
        if not juntada_data:
            return

        existing = supabase.table("votos_sorteo").select("*")\
            .eq("juntada_id", juntada_id).eq("telegram_id", telegram_id).execute().data

        if existing:
            supabase.table("votos_sorteo").update({"voto": voto})\
                .eq("juntada_id", juntada_id).eq("telegram_id", telegram_id).execute()
        else:
            supabase.table("votos_sorteo").insert({
                "juntada_id": juntada_id,
                "telegram_id": telegram_id,
                "participante": nombre,
                "voto": voto
            }).execute()

        participantes = get_participantes(chat_id)
        votos = supabase.table("votos_sorteo").select("*").eq("juntada_id", juntada_id).execute().data

        total_si = sum(1 for v in votos if v["voto"] == "si")
        total_no = sum(1 for v in votos if v["voto"] == "no")

        if total_no > 0:
            await query.edit_message_text(f"Sorteo rechazado ❌\nSI:{total_si} NO:{total_no}")
            return

        if len(votos) == len(participantes):
            await query.edit_message_text("Sorteo confirmado ✅")
            return

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
            InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
        ]])

        await query.edit_message_text(
            f"Votos: SI {total_si} | NO {total_no}",
            reply_markup=keyboard
        )

    except Exception:
        logging.exception("ERROR VOTO SORTEO")
        await update.callback_query.answer("Error al votar", show_alert=True)

# ================= MAIN =================

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("sortear", sortear))

    app.add_handler(CallbackQueryHandler(manejar_menu, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(manejar_voto_sorteo, pattern="^sorteo_"))

    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()