"""
listener.py — telethon: escucha el canal del senalero y pasa el texto crudo al callback. (§10, §11)

Usa una cuenta de USUARIO (TG_API_ID / TG_API_HASH de my.telegram.org), no un bot:
los bots no pueden leer canales ajenos. El primer arranque pide login (telefono + codigo).
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telethon import TelegramClient, events

import config

# Callback recibe (texto, id_mensaje). El id permite deduplicar entre el handler en vivo
# y el polling fallback (main.py), para no procesar dos veces la misma senal.
OnMessage = Callable[[str, int], Awaitable[None]]


def channel_ref(raw: str | None = None):
    """
    Id numerico de canal (ej. '-1001803023509') -> int. Telethon NO resuelve un id negativo
    pasado como string en el filtro chats= (lanza 'Cannot find any entity corresponding to ...');
    como int lo resuelve desde la cache de entidades (get_dialogs). Un '@username' queda string.
    """
    if raw is None:
        raw = config.TG_CHANNEL
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw


# Alias interno retrocompatible.
_channel_ref = channel_ref


def build_client(on_message: OnMessage) -> TelegramClient:
    """
    Crea el cliente telethon y registra el handler de mensajes nuevos del canal.

    catch_up=True: al reconectar tras una caida, telethon pide los updates perdidos en vez de
    arrancar limpio. Es la primera defensa contra perder senales; el polling de main.py es la
    segunda (garantiza cero perdidas aunque el stream de updates falle).
    """
    client = TelegramClient(
        config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH,
        catch_up=True,
        connection_retries=None,   # reintentar conexion indefinidamente
        retry_delay=5,
    )

    @client.on(events.NewMessage(chats=channel_ref()))
    async def _handler(event) -> None:  # noqa: ANN001 - tipo de telethon
        text = event.raw_text or ""
        await on_message(text, int(event.id))

    return client
