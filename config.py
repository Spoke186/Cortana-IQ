"""
config.py — carga .env y expone constantes del bot.

Filosofia (§5, §14): parametros default-off, numeros auditables, cero secretos en codigo.
Todo lo de dinero es Decimal, no float, para que los centavos sean exactos.
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# Carga .env del directorio del proyecto (si existe). override=False: el entorno gana.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH, override=False)


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _opt_decimal(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default).strip() or default
    return Decimal(raw)


def _opt_stop_loss(name: str) -> Decimal | None:
    """STOP_LOSS_BALANCE: 'None'/'' -> None (desactivado). Numero -> Decimal."""
    raw = os.getenv(name, "None").strip()
    if raw == "" or raw.lower() == "none":
        return None
    return Decimal(raw)


def _opt_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


# NOTA: las credenciales se leen sin reventar al importar (asi corren las herramientas
# offline: dryrun.py, metrics.py, tests). La PRESENCIA se exige en validate(), que main()
# llama al arrancar, antes de tocar IQ Option o Telegram con dinero real.

# ----------------------------------------------------------------------
#  Telethon (lectura del canal)
# ----------------------------------------------------------------------
TG_API_ID: int = _opt_int("TG_API_ID")
TG_API_HASH: str = _opt("TG_API_HASH")
TG_CHANNEL: str = _opt("TG_CHANNEL")
TG_SESSION: str = _opt("TG_SESSION", "telegram_signal_listener")

# ----------------------------------------------------------------------
#  IQ Option (broker activo: turbo options 5 min)
# ----------------------------------------------------------------------
IQ_EMAIL: str = _opt("IQ_EMAIL")
IQ_PASSWORD: str = os.getenv("IQ_PASSWORD", "")  # password puede llevar espacios -> sin .strip()
IQ_ACCOUNT_TYPE: str = _opt("IQ_ACCOUNT_TYPE", "practice")  # practice | real

# ----------------------------------------------------------------------
#  Bot de avisos
# ----------------------------------------------------------------------
NOTIFY_BOT_TOKEN: str = _opt("NOTIFY_BOT_TOKEN")
NOTIFY_CHAT_ID: str = _opt("NOTIFY_CHAT_ID")

# ----------------------------------------------------------------------
#  Trading
# ----------------------------------------------------------------------
INITIAL_STAKE: Decimal = _opt_decimal("INITIAL_STAKE", "1.00")

# Niveles de Gale: entrada (0) + Gale 1 + Gale 2 == 2 niveles de gale (§4.3). FIJO.
MAX_GALE_LEVELS: int = 2

# Cada contrato Rise/Fall dura 5 minutos exactos (§3). FIJO.
CONTRACT_DURATION: int = 5
CONTRACT_DURATION_UNIT: str = "m"

# Separacion entre niveles: entrada+5 = Gale1, entrada+10 = Gale2 (§4.3).
GALE_STEP_MINUTES: int = 5

SIGNAL_TIMEZONE: str = _opt("SIGNAL_TIMEZONE", "America/Sao_Paulo")
DISPLAY_TIMEZONE: str = _opt("DISPLAY_TIMEZONE", "America/Bogota")

# 'ceil' (default, regla §4.1) | 'nearest' (tabla §4.2) | 'floor'
GALE_ROUNDING: str = _opt("GALE_ROUNDING", "ceil").lower()

# Circuit breaker preparado pero apagado por defecto (§5).
STOP_LOSS_BALANCE: Decimal | None = _opt_stop_loss("STOP_LOSS_BALANCE")

# Margen para distinguir "senal vencida" de "senal de manana" en el cruce de medianoche (§2).
STALE_SIGNAL_HOURS: int = int(_opt("STALE_SIGNAL_HOURS", "12"))

# ----------------------------------------------------------------------
#  Logs
# ----------------------------------------------------------------------
LOG_DIR: Path = Path(_opt("LOG_DIR", "logs"))
LEVELS_CSV: Path = LOG_DIR / "levels.csv"
CYCLES_CSV: Path = LOG_DIR / "cycles.csv"
ERRORS_LOG: Path = LOG_DIR / "errors.log"


def validate() -> None:
    """
    Chequeos de coherencia al arranque (§14: numeros precisos).
    Aqui se EXIGEN las credenciales (no al importar), para que las herramientas offline corran.
    """
    faltan = [
        name for name, val in (
            ("TG_API_ID", TG_API_ID), ("TG_API_HASH", TG_API_HASH), ("TG_CHANNEL", TG_CHANNEL),
            ("IQ_EMAIL", IQ_EMAIL), ("IQ_PASSWORD", IQ_PASSWORD),
            ("NOTIFY_BOT_TOKEN", NOTIFY_BOT_TOKEN), ("NOTIFY_CHAT_ID", NOTIFY_CHAT_ID),
        )
        if not val
    ]
    if faltan:
        raise RuntimeError(f"Faltan variables en .env: {', '.join(faltan)} (ver .env.example)")
    if IQ_ACCOUNT_TYPE.lower() not in ("practice", "real"):
        raise RuntimeError(f"IQ_ACCOUNT_TYPE invalido: {IQ_ACCOUNT_TYPE!r} (usa practice|real)")
    if GALE_ROUNDING not in ("ceil", "nearest", "floor"):
        raise RuntimeError(f"GALE_ROUNDING invalido: {GALE_ROUNDING!r} (usa ceil|nearest|floor)")
    if INITIAL_STAKE <= 0:
        raise RuntimeError(f"INITIAL_STAKE debe ser > 0, es {INITIAL_STAKE}")
    if STOP_LOSS_BALANCE is not None and STOP_LOSS_BALANCE < 0:
        raise RuntimeError("STOP_LOSS_BALANCE no puede ser negativo")
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def summary() -> str:
    """Resumen legible para imprimir al arranque (sin secretos)."""
    cb = "DESACTIVADO" if STOP_LOSS_BALANCE is None else f"${STOP_LOSS_BALANCE}"
    return (
        "Config:\n"
        f"  Stake inicial      : ${INITIAL_STAKE}\n"
        f"  Niveles de Gale    : {MAX_GALE_LEVELS} (entrada + Gale 1 + Gale 2)\n"
        f"  Redondeo Gale      : {GALE_ROUNDING}\n"
        f"  Duracion contrato  : {CONTRACT_DURATION} {CONTRACT_DURATION_UNIT}\n"
        f"  TZ senal           : {SIGNAL_TIMEZONE}\n"
        f"  TZ display         : {DISPLAY_TIMEZONE}\n"
        f"  Circuit breaker    : {cb}\n"
        f"  Canal              : {TG_CHANNEL}\n"
        f"  Broker             : IQ Option (turbo)\n"
        f"  Cuenta IQ          : {IQ_ACCOUNT_TYPE}\n"
    )
