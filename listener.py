"""
listener.py — telethon: escucha los canales de los senaleros y pasa el texto crudo al callback. (§10, §11)

Usa una cuenta de USUARIO (TG_API_ID / TG_API_HASH de my.telegram.org), no un bot:
los bots no pueden leer canales ajenos. El primer arranque pide login (telefono + codigo).

Multicanal (2026-07-11): escucha TODOS los canales del registro de providers y pasa el
chat_id al callback para que main.py enrute al proveedor correcto.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from telethon import TelegramClient, events

import config
import providers

# Callback recibe (texto, id_mensaje, chat_id). El id es unico POR CHAT; el dedup en main.py
# se hace por (chat_id, id). chat_id elige el proveedor (TZ/parser/gale/stake).
OnMessage = Callable[[str, int, int], Awaitable[None]]


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


def all_channel_refs() -> list[int]:
    """Todos los ids de canal del registro (para el filtro chats= y el polling)."""
    return providers.all_channel_ids()


def build_client(on_message: OnMessage) -> TelegramClient:
    """
    Crea el cliente telethon y registra los handlers de mensajes nuevos y EDITADOS de TODOS
    los canales del registro.

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

    chats = all_channel_refs()

    @client.on(events.NewMessage(chats=chats))
    async def _handler(event) -> None:  # noqa: ANN001 - tipo de telethon
        text = event.raw_text or ""
        await on_message(text, int(event.id), int(event.chat_id))

    # Los canales EDITAN sus posts tras publicarlos (meten resultados ✅/❎, corrigen typos).
    # Escuchar ediciones evita quedarse con la primera version; el dedup id+texto (main) solo
    # reprocesa si el texto cambio, y el guard por cycle_id evita programar el ciclo dos veces.
    @client.on(events.MessageEdited(chats=chats))
    async def _edit_handler(event) -> None:  # noqa: ANN001 - tipo de telethon
        text = event.raw_text or ""
        await on_message(text, int(event.id), int(event.chat_id))

    return client
