"""
dryrun.py — prueba OFFLINE. Pega un mensaje y ve que haria el bot. Sin red, sin dinero, sin creds.

Sirve para confirmar dos cosas que pidio Esteban:
  1. Que el bot SABE cual mensaje es la senal (y cual ignora).
  2. Que horas/apuestas planearia (sin tocar IQ Option).

Uso:
    python dryrun.py "USD/TRY;00:45;PUT 🟥"
    python dryrun.py            # luego pega el texto y Ctrl+Z + Enter (Windows)
"""
from __future__ import annotations

import sys
from decimal import Decimal
from zoneinfo import ZoneInfo

# La consola de Windows es cp1252 y revienta con emojis. Forzar UTF-8 en stdout.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import config
import gale
import scheduler
from iqoption_client import to_iq_symbol
from parser import parse_signal

# Payout de REFERENCIA solo para previsualizar apuestas; en vivo se usa el real de IQ (§4.3).
REF_PAYOUT = Decimal("0.90")
_NAMES = {0: "Entrada", 1: "Gale 1", 2: "Gale 2"}


def analyze(text: str) -> None:
    print("=" * 64)
    print("MENSAJE:")
    print((text or "").strip() or "(vacio)")
    print("-" * 64)

    sig = parse_signal(text)
    if sig is None:
        print("=> NO es senal. El bot la IGNORA (no acciona nada).")
        print("=" * 64)
        return

    symbol = to_iq_symbol(sig.par)
    sentido = "Fall / Bajar" if sig.direction == "PUT" else "Rise / Subir"
    print("=> SENAL detectada:")
    print(f"   Par        : {sig.par}   ->   IQ {symbol} (turbo; -OTC si finde)")
    print(f"   Direccion  : {sig.direction}  ({sentido})")
    print(f"   Hora       : {sig.entry_hhmm}  (UTC-3, zona de la senal)")

    sched = scheduler.build_schedule(sig)
    if sched.skipped:
        print(f"   PROGRAMACION: SALTADA -> {sched.reason}")
        print("=" * 64)
        return

    sig_tz = ZoneInfo(config.SIGNAL_TIMEZONE)
    disp_tz = ZoneInfo(config.DISPLAY_TIMEZONE)
    print("   Horas de ejecucion:")
    for lvl, t in enumerate(sched.run_times_utc):
        col = t.astimezone(disp_tz).strftime("%Y-%m-%d %H:%M")
        u3 = t.astimezone(sig_tz).strftime("%H:%M")
        utc = t.strftime("%H:%M")
        print(f"     {_NAMES[lvl]:8}: {col} Col  |  {u3} UTC-3  |  {utc} UTC")

    if sched.gale_mismatch:
        print(f"   ⚠ Horas de Gale declaradas {sig.declared_gale_hhmm} no cuadran con las derivadas; se usan las derivadas.")

    plan = gale.plan_cycle(REF_PAYOUT)
    print(f"   Apuestas (payout REF {REF_PAYOUT}, redondeo '{config.GALE_ROUNDING}'):")
    for lvl, stake in enumerate(plan.stakes):
        print(f"     {_NAMES[lvl]:8}: ${stake}")
    print(f"   Meta por ciclo : ${plan.meta}")
    print(f"   Perdida total si pierde los 3: ${plan.worst_case_loss}")
    print("   (en vivo, el payout real de cada contrato puede ajustar estas cifras)")
    print("=" * 64)


def main() -> None:
    if len(sys.argv) > 1:
        analyze(" ".join(sys.argv[1:]))
    else:
        print("Pega el mensaje y termina con Ctrl+Z + Enter (Windows) / Ctrl+D (Linux):")
        analyze(sys.stdin.read())


if __name__ == "__main__":
    main()
