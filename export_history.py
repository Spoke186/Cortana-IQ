"""
export_history.py — vuelca ~62 dias del canal a history_dump.json (read-only).

SEGURO solo con el bot DETENIDO (misma sesion telethon). No pide login: si la sesion
no esta autorizada, aborta en vez de colgarse pidiendo telefono/codigo.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient

import config
from listener import channel_ref

DAYS = 62
OUT = "history_dump.json"


async def main() -> None:
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ABORT: sesion NO autorizada (no hago login interactivo).")
        await client.disconnect()
        return

    # Poblar cache de entidades para resolver el id numerico del canal.
    await client.get_dialogs()
    ch = channel_ref()

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    msgs = []
    async for m in client.iter_messages(ch):
        if m.date < cutoff:
            break
        if m.message:
            msgs.append({"id": m.id, "date": m.date.isoformat(), "text": m.message})

    await client.disconnect()

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False)

    print(f"TOTAL_MSGS={len(msgs)}")
    if msgs:
        print(f"RANGO: {msgs[-1]['date']}  ->  {msgs[0]['date']}")
    print("===== MUESTRA (40 mensajes mas recientes) =====")
    for m in msgs[:40]:
        print(f"---- id={m['id']} {m['date']}")
        print(m["text"][:400])


if __name__ == "__main__":
    asyncio.run(main())
