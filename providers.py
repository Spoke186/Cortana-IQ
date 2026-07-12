"""
providers.py — registro multi-canal. Cada proveedor de senales tiene su propio FORMATO,
zona horaria, expiracion (M1/M5), niveles de Gale y stake. (multicanal 2026-07-11)

Filosofia: el parser de cada proveedor devuelve SIEMPRE una lista de Signal (0..N). Los
canales "en vivo" (1 senal por mensaje) devuelven 0 o 1; los canales de "lista diaria"
(un mensaje con ~30 senales) devuelven N. El resto del pipeline (scheduler, run_cycle)
opera cada Signal por separado, con los parametros del proveedor que la emitio.

NORMALIZACION DE PAR: internamente todo par es "XXX/YYY" (con slash) para reusar
to_iq_symbol() y config.bucket_for(). Los canales que mandan "EURGBP" o "EURGBP-OTC"
se normalizan a "EUR/GBP" (el sufijo -OTC lo resuelve solo iqoption_client segun apertura).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

import config
from parser import Signal, parse_signal

# Fecha del header de la lista diaria:
#   CONSISTENTES: "📅 11/07/2026"     GOLD: "🗓Dia:09/07/2026🗓"
_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _resolve_entry_date(hdr: tuple[int, int, int] | None, hour: int) -> str | None:
    """
    Fecha calendario ISO de una entrada. La lista cubre un dia de trading que arranca la NOCHE
    anterior: entradas con hora >= 18 pertenecen al dia del header - 1. None si no hay header.
    """
    if hdr is None:
        return None
    d, m, y = hdr
    base = date(y, m, d)
    if hour >= 18:
        base = base - timedelta(days=1)
    return base.isoformat()


def _header_date(text: str) -> tuple[int, int, int] | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    return (d, mo, y)


# ----------------------------------------------------------------------
#  Normalizacion de par
# ----------------------------------------------------------------------
def normalize_pair(raw: str) -> str | None:
    """
    'EURGBP' -> 'EUR/GBP' ; 'EURGBP-OTC' -> 'EUR/GBP' ; 'EUR/JPY' -> 'EUR/JPY'.
    Devuelve None si no son 6 letras ISO (basura -> se ignora, no se opera).
    """
    p = raw.upper().strip()
    p = re.sub(r"-?OTC$", "", p)          # quita sufijo -OTC / OTC
    p = p.replace("/", "")
    if len(p) != 6 or not p.isalpha():
        return None
    return f"{p[:3]}/{p[3:]}"


# ----------------------------------------------------------------------
#  Parsers por proveedor (cada uno -> list[Signal])
# ----------------------------------------------------------------------
def parse_main(text: str, source: str) -> list[Signal]:
    """Canal actual (-1001803023509): en vivo, 1 senal/msg, formato PAR/PAR;HH:MM;DIR, 5min."""
    sig = parse_signal(text)
    if sig is None:
        return []
    # reetiqueta con source y duracion 5 (el par ya viene con slash del regex de parser.py)
    return [_rebrand(sig, source=source, duration_min=5)]


# CONSISTENTES VIP (-1001962455192), TZ UTC-5, lista diaria M1 y M5:
#   "⏳M1 EURGBP-OTC 22:57 PUT 🟥"   |   "⏳M5 USDJPY 01:25 PUT 🟥"
_CONSISTENTES_RE = re.compile(
    r"M(?P<dur>[15])\s+"
    r"(?P<pair>[A-Z]{3,4}/?[A-Z]{2,3}(?:-OTC)?)\s+"
    r"(?P<hora>\d{1,2}:\d{2})\s+"
    r"(?P<dir>(?i:PUT|CALL))",
)


def parse_consistentes(text: str, source: str) -> list[Signal]:
    hdr = _header_date(text)
    out: list[Signal] = []
    for m in _CONSISTENTES_RE.finditer(text):
        par = normalize_pair(m.group("pair"))
        if par is None:
            continue
        hh, mm = int(m.group("hora").split(":")[0]), int(m.group("hora").split(":")[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            continue
        out.append(Signal(
            par=par, entry_hhmm=f"{hh:02d}:{mm:02d}", direction=m.group("dir").upper(),
            raw=m.group(0), duration_min=int(m.group("dur")), source=source,
            entry_date=_resolve_entry_date(hdr, hh),
        ))
    return out


# GOLD TRADER (-1001615163577), TZ UTC-3, lista diaria (msg M1 y msg M5 separados):
#   "06:20;EURUSD;CALL;M5"  |  con prefijo fecha "07/01/2026;06:15;EURJPY;CALL;M5"
#   La linea puede terminar en emoji de resultado (✅/❎) que se ignora.
_GOLD_RE = re.compile(
    r"(?:\d{2}/\d{2}/\d{4}\s*;\s*)?"        # prefijo fecha opcional (se ignora)
    r"(?P<hora>\d{1,2}:\d{2})\s*;\s*"
    r"(?P<pair>[A-Z]{6})\s*;\s*"
    r"(?P<dir>(?i:PUT|CALL))\s*;\s*"
    r"M(?P<dur>[15])",
)


def parse_gold(text: str, source: str) -> list[Signal]:
    hdr = _header_date(text)
    out: list[Signal] = []
    for m in _GOLD_RE.finditer(text):
        par = normalize_pair(m.group("pair"))
        if par is None:
            continue
        hh, mm = int(m.group("hora").split(":")[0]), int(m.group("hora").split(":")[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            continue
        out.append(Signal(
            par=par, entry_hhmm=f"{hh:02d}:{mm:02d}", direction=m.group("dir").upper(),
            raw=m.group(0), duration_min=int(m.group("dur")), source=source,
            entry_date=_resolve_entry_date(hdr, hh),
        ))
    return out


def _rebrand(sig: Signal, *, source: str, duration_min: int) -> Signal:
    return Signal(
        par=sig.par, entry_hhmm=sig.entry_hhmm, direction=sig.direction, raw=sig.raw,
        declared_gale_hhmm=sig.declared_gale_hhmm, duration_min=duration_min, source=source,
    )


# ----------------------------------------------------------------------
#  Proveedor
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Provider:
    key: str                                   # slug corto ("main", "consistentes", "gold")
    channel_id: int                            # id numerico Telegram (-100...)
    name: str                                  # etiqueta legible
    tz: str                                    # zona horaria de la HORA de la senal
    max_gale: int                              # niveles de Gale (0 = sin martingala)
    parse_fn: Callable[[str, str], list[Signal]]
    stake_flat: Decimal | None = None          # None -> usa buckets de config (solo 'main')
    # Arranque: True = sembrar backlog como visto (canal en vivo 'main': no re-disparar senales
    # viejas). False = NO sembrar (canales de lista diaria): el poll procesa la lista de HOY y
    # programa las entradas futuras (las vencidas se saltan solas en el scheduler).
    seed_on_start: bool = True
    # Filtro de tendencia: True = no operar senales contra el trend del mercado (lo que piden los
    # grupos). False = operar siempre (canal 'main': su formato no habla de tendencia).
    trend_filter: bool = False
    # whitelist_only: True = SOLO operar los pares listados en STAKE_TABLE[key]; cualquier par
    # fuera de la lista se deshabilita (stake 0). Para proveedores perdedores en crudo donde solo
    # unos pocos pares son EV+ (CONSISTENTES).
    whitelist_only: bool = False

    def parse(self, text: str) -> list[Signal]:
        return self.parse_fn(text, self.key)

    def stake_for(self, par: str) -> Decimal:
        """Stake por MERCADO: STAKE_TABLE[proveedor][par] gana; si el par no esta y el proveedor
        es whitelist_only -> 0 (deshabilitado); si no, cae al stake plano (o bucket en 'main').
        0.00 => mercado deshabilitado."""
        tbl = config.STAKE_TABLE.get(self.key, {})
        if par in tbl:
            return tbl[par]
        if self.whitelist_only:
            return Decimal("0")
        return config.stake_for(par) if self.stake_flat is None else self.stake_flat

    def bucket_for(self, par: str) -> str:
        return config.bucket_for(par) if self.stake_flat is None else self.key


def _as_int(raw) -> int:
    """Convierte a int tolerando vacio/None (herramientas offline sin .env): 0 = desactivado."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


# Registro. 'main' conserva TZ/stake/gale actuales; los nuevos entran en DEMO.
def build_registry() -> dict[int, Provider]:
    provs = [
        Provider(
            key="main", channel_id=_as_int(config.TG_CHANNEL), name="Canal principal",
            tz=config.SIGNAL_TIMEZONE, max_gale=config.MAX_GALE_LEVELS,
            parse_fn=parse_main, stake_flat=None,   # buckets por par
        ),
        Provider(
            key="consistentes", channel_id=config.TG_CH_CONSISTENTES,
            name="SEÑALES CONSISTENTES VIP", tz=config.TZ_CONSISTENTES,
            max_gale=config.GALE_CONSISTENTES, parse_fn=parse_consistentes,
            stake_flat=config.STAKE_CONSISTENTES, seed_on_start=False,
            trend_filter=True, whitelist_only=True,   # crudo perdedor: solo whitelist + trend
        ),
        Provider(
            key="gold", channel_id=config.TG_CH_GOLD,
            name="Señales VIP GOLD TRADER", tz=config.TZ_GOLD,
            max_gale=config.GALE_GOLD, parse_fn=parse_gold,
            stake_flat=config.STAKE_GOLD, seed_on_start=False,
            trend_filter=False,   # WR 70% sin gale; filtro EMA no validado aqui -> no gatear
        ),
    ]
    return {p.channel_id: p for p in provs if p.channel_id}


REGISTRY: dict[int, Provider] = build_registry()


def provider_for(channel_id: int) -> Provider | None:
    return REGISTRY.get(channel_id)


def all_channel_ids() -> list[int]:
    return list(REGISTRY.keys())
