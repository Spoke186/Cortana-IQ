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
TG_CHANNEL: str = _opt("TG_CHANNEL")          # canal principal ('main'), retrocompatible
TG_SESSION: str = _opt("TG_SESSION", "telegram_signal_listener")

# ----------------------------------------------------------------------
#  Multicanal (2026-07-11): 2 proveedores extra en DEMO. 0/'' = desactivado.
#  Cada proveedor tiene su TZ, expiracion (M1/M5 en el mensaje), Gale y stake propios.
# ----------------------------------------------------------------------
TG_CH_CONSISTENTES: int = _opt_int("TG_CH_CONSISTENTES")   # SEÑALES CONSISTENTES VIP (UTC-5)
TG_CH_GOLD: int = _opt_int("TG_CH_GOLD")                   # GOLD TRADER (UTC-3, sin martingala)

# TZ por proveedor. UTC-5 sin DST = America/Bogota; UTC-3 = America/Sao_Paulo.
TZ_CONSISTENTES: str = _opt("TZ_CONSISTENTES", "America/Bogota")
TZ_GOLD: str = _opt("TZ_GOLD", "America/Sao_Paulo")

# Gale por proveedor (decision Esteban 2026-07-11): consistentes=2, gold=0 ('sin martingala').
GALE_CONSISTENTES: int = _opt_int("GALE_CONSISTENTES", 2)
GALE_GOLD: int = _opt_int("GALE_GOLD", 0)

# Stake plano por proveedor nuevo (fallback si el par no esta en STAKE_TABLE).
STAKE_CONSISTENTES: Decimal = _opt_decimal("STAKE_CONSISTENTES", "6.00")   # irrelevante: whitelist_only
STAKE_GOLD: Decimal = _opt_decimal("STAKE_GOLD", "10.00")                  # pares gold sin override

# ----------------------------------------------------------------------
#  Stake por MERCADO (proveedor -> par -> stake). Basado en analisis de WR (2026-07-11).
#  Un par en 0.00 => NO operar ese mercado (perdedor). Par ausente => stake plano del proveedor
#  (o bucket, en 'main'). Editar aqui; es infra, no secreto.
# ----------------------------------------------------------------------
_D = Decimal
STAKE_TABLE: dict[str, dict[str, Decimal]] = {
    # GOLD: WR ~70% en 3 majors, SIN gale -> riesgo por trade = stake (no multiplica). Bankroll $850.
    "gold": {
        "EUR/JPY": _D("25.00"),   # 73%
        "EUR/USD": _D("18.00"),   # 69%
        "GBP/USD": _D("18.00"),   # 68%
    },
    # CONSISTENTES: crudo PERDEDOR (48.7%). Whitelist EV+ CON filtro de tendencia. 2 gale -> peor
    # ~8x. base 8 -> peor ~$62 (7% de $850). Resto deshabilitado (whitelist_only).
    "consistentes": {
        "EUR/GBP": _D("8.00"),   # 64.7% a-favor (n=85)
        "GBP/AUD": _D("6.00"),   # 64.1% (n=39, muestra chica)
        "EUR/USD": _D("6.00"),   # 59.6% (n=57)
        "EUR/NZD": _D("6.00"),   # 57.1% (n=28, muestra chica)
    },
    # main: EV-negativo -> corta perdedores (0) y sube SOLO los ganadores probados; resto bucket.
    "main": {
        "USD/CHF": _D("0.00"), "CAD/JPY": _D("0.00"), "USD/PHP": _D("0.00"),
        "USD/COP": _D("0.00"), "USD/BRL": _D("0.00"),   # perdedores <45% WR
        "USD/BDT": _D("7.00"), "USD/INR": _D("7.00"), "CAD/CHF": _D("7.00"),  # ganadores >65% (peor ~$54)
    },
}

# ----------------------------------------------------------------------
#  Filtro de tendencia (grupos: "no opere contra tendencia"). EMA rapida vs lenta en la TF
#  de la senal (M1->60s, M5->300s). Si la senal va CONTRA el trend medido a la hora de entrada
#  -> NO se opera. Activo por proveedor (ver providers.py).
# ----------------------------------------------------------------------
TREND_EMA_FAST: int = _opt_int("TREND_EMA_FAST", 9)
TREND_EMA_SLOW: int = _opt_int("TREND_EMA_SLOW", 21)

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
INITIAL_STAKE: Decimal = _opt_decimal("INITIAL_STAKE", "1.00")  # legacy/fallback; el stake real es por bucket

# Stakes por bucket — corrida DEMO de recoleccion (handoff 2026-06-23). Real > OTC; alto en los
# 2 pares de mejor EV (AUD/JPY, AUD/CAD). NO subir de 12 (un ciclo reventado AUD ~= 3.9% del cap).
_MAJORS = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
HIGH_STAKE_PAIRS = {"AUD/JPY", "AUD/CAD"}
# BANKROLL $850 (2026-07-11). Sizeo para que el peor ciclo (2 gale ~8x base) <= ~7% del bank.
# GOLD (sin gale, riesgo=stake) lleva los stakes grandes; los de 2-gale van chicos.
STAKE_ALTO: Decimal = _opt_decimal("STAKE_ALTO", "8.00")    # AUD/JPY, AUD/CAD (main) -> peor ~$62
STAKE_REAL: Decimal = _opt_decimal("STAKE_REAL", "5.00")    # main majors sin override -> peor ~$39
STAKE_OTC: Decimal = _opt_decimal("STAKE_OTC", "3.00")      # main exoticos sin override -> peor ~$23


def is_real_pair(par: str) -> bool:
    """REAL = ambas monedas son majors (transfiere de Quotex a IQ); OTC = exotico/sintetico."""
    try:
        a, b = par.upper().split("/")
    except ValueError:
        return False
    return a in _MAJORS and b in _MAJORS


def bucket_for(par: str) -> str:
    return "REAL" if is_real_pair(par) else "OTC"


def stake_for(par: str) -> Decimal:
    """Stake de ENTRADA segun bucket. El Gale se dimensiona sobre este con la meta-constante."""
    p = par.upper()
    if p in HIGH_STAKE_PAIRS:
        return STAKE_ALTO
    return STAKE_REAL if is_real_pair(p) else STAKE_OTC


# Niveles de Gale. Demo-recoleccion 2026-06-23: bajado a 1 (G=0 colapso OOS; G=2 ya no se opera).
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
#  Robustez (red inestable: telethon e IQ se caen y reconectan)
# ----------------------------------------------------------------------
# Polling fallback de Telegram: cada N seg releemos los ultimos mensajes del canal y
# procesamos los que el handler en vivo se haya perdido durante una desconexion. Dedup por id.
POLL_INTERVAL_SECONDS: int = int(_opt("POLL_INTERVAL_SECONDS", "30"))
POLL_LIMIT: int = int(_opt("POLL_LIMIT", "15"))

# Keep-alive IQ Option: cada N seg verificamos la conexion y reconectamos si cayo,
# para que IQ este listo cuando dispare una senal (la lib se cae sola seguido).
IQ_KEEPALIVE_SECONDS: int = int(_opt("IQ_KEEPALIVE_SECONDS", "30"))

# ----------------------------------------------------------------------
#  Logs
# ----------------------------------------------------------------------
LOG_DIR: Path = Path(_opt("LOG_DIR", "logs"))
LEVELS_CSV: Path = LOG_DIR / "levels.csv"
CYCLES_CSV: Path = LOG_DIR / "cycles.csv"
ERRORS_LOG: Path = LOG_DIR / "errors.log"
DEMO_CSV: Path = LOG_DIR / "demo_entries.csv"   # log de recoleccion (1 fila por ciclo, con ATR)


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
    for nm, val in (("STAKE_ALTO", STAKE_ALTO), ("STAKE_REAL", STAKE_REAL), ("STAKE_OTC", STAKE_OTC)):
        if val <= 0:
            raise RuntimeError(f"{nm} debe ser > 0, es {val}")
    if STOP_LOSS_BALANCE is not None and STOP_LOSS_BALANCE < 0:
        raise RuntimeError("STOP_LOSS_BALANCE no puede ser negativo")
    # Multicanal: TZs cargables y sin ids de canal duplicados entre proveedores.
    from zoneinfo import ZoneInfo
    for nm, tz in (("TZ_CONSISTENTES", TZ_CONSISTENTES), ("TZ_GOLD", TZ_GOLD)):
        try:
            ZoneInfo(tz)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{nm} zona horaria invalida: {tz!r} ({exc})")
    ids = [i for i in (_opt_int_safe(TG_CHANNEL), TG_CH_CONSISTENTES, TG_CH_GOLD) if i]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"ids de canal duplicados entre proveedores: {ids}")
    for nm, val in (("STAKE_CONSISTENTES", STAKE_CONSISTENTES), ("STAKE_GOLD", STAKE_GOLD)):
        if val <= 0:
            raise RuntimeError(f"{nm} debe ser > 0, es {val}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _opt_int_safe(raw) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def summary() -> str:
    """Resumen legible para imprimir al arranque (sin secretos)."""
    cb = "DESACTIVADO" if STOP_LOSS_BALANCE is None else f"${STOP_LOSS_BALANCE}"
    return (
        "Config:\n"
        f"  Stakes (bucket)    : Alto ${STAKE_ALTO} (AUD/JPY,AUD/CAD) | REAL ${STAKE_REAL} | OTC ${STAKE_OTC}\n"
        f"  Niveles de Gale    : {MAX_GALE_LEVELS} (entrada + Gale 1 + Gale 2)\n"
        f"  Redondeo Gale      : {GALE_ROUNDING}\n"
        f"  Duracion contrato  : {CONTRACT_DURATION} {CONTRACT_DURATION_UNIT}\n"
        f"  TZ senal           : {SIGNAL_TIMEZONE}\n"
        f"  TZ display         : {DISPLAY_TIMEZONE}\n"
        f"  Circuit breaker    : {cb}\n"
        f"  Canal principal    : {TG_CHANNEL} (TZ {SIGNAL_TIMEZONE}, {MAX_GALE_LEVELS} gale)\n"
        f"  + CONSISTENTES     : {TG_CH_CONSISTENTES or 'off'} (TZ {TZ_CONSISTENTES}, {GALE_CONSISTENTES} gale, M1+M5, whitelist {list(STAKE_TABLE.get('consistentes', {}))}, filtro-tendencia ON)\n"
        f"  + GOLD TRADER      : {TG_CH_GOLD or 'off'} (TZ {TZ_GOLD}, {GALE_GOLD} gale, M1+M5, stake fuerte {list(STAKE_TABLE.get('gold', {}))}, filtro-tendencia OFF)\n"
        f"  Filtro tendencia   : EMA {TREND_EMA_FAST}/{TREND_EMA_SLOW} en TF de la senal\n"
        f"  main deshabilitados: {[p for p,s in STAKE_TABLE.get('main', {}).items() if s == 0]}\n"
        f"  Broker             : IQ Option (turbo)\n"
        f"  Cuenta IQ          : {IQ_ACCOUNT_TYPE}\n"
    )
