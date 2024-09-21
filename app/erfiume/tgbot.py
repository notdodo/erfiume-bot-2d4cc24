"""
Handle bot intections with users.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from inspect import cleandoc
from typing import TYPE_CHECKING, Any

import boto3
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from .apis import Stazione

from .logging import logger
from .storage import DynamoClient


async def fetch_bot_token() -> str:
    """
    Fetch the Telegram Bot token from AWS SM
    """
    environment = os.getenv("ENVIRONMENT", "staging")
    return boto3.client(
        service_name="secretsmanager",
        endpoint_url=("http://localhost:4566" if environment != "production" else None),
    ).get_secret_value(
        SecretId="telegram-bot-token",
    )["SecretString"]


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    if update.message and user:
        await update.message.reply_html(
            rf"Ciao {user.mention_html()}! Scrivi il nome di una stazione da monitorare per iniziare (e.g. <b>Cesena</b>)",
        )


def create_station_message(station: Stazione) -> str:
    """
    Create and format the answer from the bot.
    """
    timestamp = (
        datetime.fromtimestamp(
            int(station.timestamp) / 1000, tz=ZoneInfo("Europe/Rome")
        )
        .replace(tzinfo=None)
        .strftime("%d-%m-%Y %H:%M")
    )
    value = float(station.value)
    yellow = station.soglia1
    orange = station.soglia2
    red = station.soglia3
    alarm = "🔴"
    if value <= yellow:
        alarm = "🟢"
    elif value > yellow and value <= orange:
        alarm = "🟡"
    elif value >= orange and value <= red:
        alarm = "🟠"
    return cleandoc(
        f"""Stazione: {station.nomestaz}
            Valore: {value!r} {alarm}
            Soglia Gialla: {yellow}
            Soglia Arancione: {orange}
            Soglia Rossa: {red}
            <b>Ultimo rilevamento: {timestamp}</b>"""
    )


async def cesena(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /cesena is issued."""
    db_client = await DynamoClient.create()
    stazione = await db_client.get_matching_station("Cesena")
    if stazione:
        if update.message:
            await update.message.reply_html(create_station_message(stazione))
    elif update.message:
        await update.message.reply_html(
            "Nessun stazione trovata!",
        )


async def handle_private_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle messages writte from private chat to match a specific station
    """

    message = cleandoc(
        """Stazione non trovata!
        Inserisci esattamente il nome che vedi dalla pagina https://allertameteo.regione.emilia-romagna.it/livello-idrometrico
        Ad esempio 'Cesena', 'Lavino di Sopra' o 'S. Carlo'"""
    )
    if update.message and update.effective_chat and update.message.text:
        logger.info("Received private message: %s", update.message.text)
        db_client = await DynamoClient.create()
        stazione = await db_client.get_matching_station(update.message.text)
        if stazione and update.message:
            message = create_station_message(stazione)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
        )


async def bot(event: dict[str, Any]) -> None:
    """Run entry point for the bot"""
    application = Application.builder().token(await fetch_bot_token()).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cesena", cesena))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.TEXT | filters.COMMAND),
            handle_private_message,
        )
    )

    # Decode the incoming Telegram message
    if event.get("body"):
        update_dict = json.loads(event["body"])
        async with application:
            update = Update.de_json(update_dict, application.bot)
            await application.process_update(update)
