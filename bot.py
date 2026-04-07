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

# CONFIG
TOKEN = os.getenv("TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
logging.basicConfig(level=logging.INFO)

(
    ESPERANDO_DIA, ESPERANDO_HORA,
    ESPERANDO_PELICULA, ESPERANDO_ALBUM
) = range(4)

# HELPERS

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

# START

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

# ============================
# (TODO tu código original intacto hasta sorteo)
# ============================

# 🔥 SOLO ESTA FUNCIÓN CAMBIÓ

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
        else:
            juntada_id = int(data.replace("sorteo_no_", ""))
            voto = "no"

        juntada_data = supabase.table("juntadas").select("*").eq("id", juntada_id).execute().data
        if not juntada_data or juntada_data[0]["estado"] != "votando_sorteo":
            await query.answer("Esta votación ya no está activa.", show_alert=True)
            return

        j = juntada_data[0]

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
                f"🔄 Sorteo rechazado.\n\n"
                f"✅ {total_si} | ❌ {total_no}"
            )
            return

        if len(votos) >= total_part and total_si == total_part:
            supabase.table("juntadas").update({"estado": "sorteo_confirmado"}).eq("id", juntada_id).execute()
            await query.edit_message_text(
                f"✅ Sorteo confirmado!\n\n"
                f"🎬 {peli_txt}\n🎵 {album_txt}"
            )
            return

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Me copa", callback_data=f"sorteo_si_{juntada_id}"),
            InlineKeyboardButton("👎 Resortear", callback_data=f"sorteo_no_{juntada_id}")
        ]])

        await query.edit_message_text(
            f"🎲 Sorteo activo\n\n"
            f"🎬 {peli_txt}\n🎵 {album_txt}\n\n"
            f"✅ {total_si} | ❌ {total_no}\n"
            f"Faltan: {total_part - len(votos)}",
            reply_markup=keyboard
        )

    except Exception:
        logging.exception("ERROR VOTO SORTEO")
        await update.callback_query.answer("Error al votar", show_alert=True)