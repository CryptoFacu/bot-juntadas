# (archivo recortado por espacio en este entorno)
# Te dejo SOLO la parte modificada clave: manejar_voto_sorteo corregido

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

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
        if not juntada_data or juntada_data[0]["estado"] != "votando_sorteo":
            await query.answer("Esta votación ya no está activa.", show_alert=True)
            return

        j = juntada_data[0]

        existing = supabase.table("votos_sorteo").select("*")             .eq("juntada_id", juntada_id).eq("telegram_id", telegram_id).execute().data

        if existing:
            supabase.table("votos_sorteo").update({"voto": voto})                 .eq("juntada_id", juntada_id).eq("telegram_id", telegram_id).execute()
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
                f"🔄 Sorteo rechazado. Pueden hacer /sortear para un nuevo sorteo.\n\n"
                f"✅ A favor: {total_si} | ❌ En contra: {total_no}"
            )
            return

        if len(votos) >= total_part and total_si == total_part:
            supabase.table("juntadas").update({"estado": "sorteo_confirmado"}).eq("id", juntada_id).execute()
            await query.edit_message_text(
                f"✅ ¡Sorteo confirmado por unanimidad!\n\n"
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

    except Exception:
        logging.exception("Error en manejar_voto_sorteo")
        await update.callback_query.answer("Hubo un error al votar.", show_alert=True)
