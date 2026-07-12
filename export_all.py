import asyncio, json
from telethon import TelegramClient
import config
from listener import channel_ref

OUT = "history_dump_full.json"

async def main():
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ABORT: sesion NO autorizada"); await client.disconnect(); return
    await client.get_dialogs()
    ch = channel_ref()
    msgs = []
    async for m in client.iter_messages(ch):
        if m.message:
            msgs.append({"id": m.id, "date": m.date.isoformat(), "text": m.message})
    await client.disconnect()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False)
    print(f"TOTAL_MSGS={len(msgs)}")
    if msgs:
        print(f"RANGO: {msgs[-1]['date']} -> {msgs[0]['date']}")
        print(f"ID_RANGE: {msgs[-1]['id']} -> {msgs[0]['id']}")

asyncio.run(main())
