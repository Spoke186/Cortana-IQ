import asyncio, json, sys, time
from telethon import TelegramClient
import config
from listener import channel_ref

OUT = "history_dump_full.json"
PROGRESS = "/tmp/exp_progress.txt"

def note(s):
    with open(PROGRESS, "a") as f:
        f.write(s + "\n")
    print(s, flush=True)

async def main():
    note(f"START {time.strftime('%H:%M:%S')}")
    client = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        note("ABORT: sesion NO autorizada"); await client.disconnect(); return
    note("connected, get_dialogs...")
    await client.get_dialogs()
    ch = channel_ref()
    note("iterating...")
    msgs = []
    n = 0
    async for m in client.iter_messages(ch):
        if m.message:
            msgs.append({"id": m.id, "date": m.date.isoformat(), "text": m.message})
        n += 1
        if n % 2000 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(msgs, f, ensure_ascii=False)
            note(f"  {n} msgs scanned, kept {len(msgs)}, oldest {msgs[-1]['date'][:10] if msgs else '?'}")
    await client.disconnect()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False)
    note(f"DONE total_scanned={n} kept={len(msgs)}")
    if msgs:
        note(f"RANGE {msgs[-1]['date']} -> {msgs[0]['date']}")

asyncio.run(main())
