"""
diag.py — diagnostico puntual (NO parte del bot): que señales mando el canal hoy y
si esos pares existen / estan abiertos en IQ Option (turbo) AHORA mismo.

Lee el canal con la sesion de telethon y consulta IQ. Correr SOLO con el bot detenido
(comparten la sesion de telethon). Imprime una tabla; no opera nada.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from listener import channel_ref
from parser import parse_signal
from telethon import TelegramClient

import iqoption_client as bk
import iqoptionapi.constants as OP_code

N_MSGS = 60  # cuantos mensajes recientes del canal revisar


async def read_channel_signals():
    c = TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)
    await c.connect()
    await c.get_dialogs()
    msgs = await c.get_messages(channel_ref(), limit=N_MSGS)
    await c.disconnect()

    sigs = []
    for m in reversed(msgs):  # cronologico
        text = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
        s = parse_signal(text)
        if s:
            sigs.append((m.date, s.par, s.entry_hhmm, s.direction))
    return sigs, len(msgs)


def iq_status_for(iq, par: str):
    """(existe_en_constantes, abierto_ahora, asset_usado)."""
    base = par.replace("/", "").upper()
    cands = [x for x in (base, f"{base}-OTC") if x in OP_code.ACTIVES]
    if not cands:
        return False, False, None
    ot = iq.get_all_open_time()
    turbo = ot.get("turbo", {})
    for x in cands:
        if turbo.get(x, {}).get("open"):
            return True, True, x
    return True, False, cands[0]


async def main():
    print(f"AHORA UTC: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} (dia semana: {datetime.now(timezone.utc):%A})")
    print(f"Revisando ultimos {N_MSGS} mensajes del canal...\n")

    sigs, n = await read_channel_signals()
    print(f"Mensajes leidos: {n} | con formato de SEÑAL: {len(sigs)}\n")

    # Conectar IQ una vez
    client = bk.IQClient()
    await client.connect()
    iq = client.iq

    # Pares unicos
    pares = []
    for _, par, _, _ in sigs:
        if par not in pares:
            pares.append(par)

    print("=== SEÑALES DEL CANAL (cronologico) ===")
    for dt, par, hhmm, dirn in sigs:
        print(f"  {dt:%H:%M} msg | {par:9s} entrada {hhmm} {dirn}")

    print("\n=== DISPONIBILIDAD EN IQ (turbo, AHORA) ===")
    print(f"  {'PAR':10s} {'existe IQ':10s} {'abierto':8s} asset")
    for par in pares:
        exists, is_open, asset = await asyncio.get_running_loop().run_in_executor(
            None, iq_status_for, iq, par
        )
        ex = "SI" if exists else "NO"
        op = "SI" if is_open else "no"
        print(f"  {par:10s} {ex:10s} {op:8s} {asset}")

    # Que hay abierto en IQ turbo ahora (panorama fin de semana)
    ot = await asyncio.get_running_loop().run_in_executor(None, iq.get_all_open_time)
    turbo = ot.get("turbo", {})
    abiertos = sorted([k for k, v in turbo.items() if v.get("open")])
    print(f"\n=== IQ turbo ABIERTOS ahora ({len(abiertos)}) ===")
    print("  " + (", ".join(abiertos) if abiertos else "(ninguno)"))


if __name__ == "__main__":
    asyncio.run(main())
