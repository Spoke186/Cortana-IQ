"""
listener.py — telethon: escucha el canal del senalero y pasa el texto crudo al callback. (§10, §11)

Usa una cuenta de USUARIO (TG_API_ID / TG_API_HASH de my.telegram.org), no un bot:
los bots no pueden leer canales ajenos. El primer arranque pide login (telefono + codigo).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telethon import TelegramClient, events

import config

OnText = Callable[[str], Awaitable[None]]


def build_client(on_text: OnText) -> TelegramClient:
    """Crea el cliente telethon y registra el handler de mensajes nuevos del canal."""
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)

    @client.on(events.NewMessage(chats=config.TG_CHANNEL))
    async def _handler(event) -> None:  # noqa: ANN001 - tipo de telethon
        text = event.raw_text or ""
        await on_text(text)

    return client
