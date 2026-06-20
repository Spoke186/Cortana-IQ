"""
logger.py — CSV auditable por NIVEL y por CICLO, + errors.log (§9).

Proposito central (§9, §14): medir el WR CRUDO por entrada (no el inflado por Gale).
Numeros crudos, append-only, sin narrativa. Cada fila es un hecho verificable.
"""
from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import config

_LOCK = threading.Lock()  # los appends pueden venir de tasks concurrentes

LEVEL_FIELDS = [
    "ts_utc", "cycle_id", "par", "iq_symbol", "direction", "level",
    "stake", "payout_fraction", "entry_spot", "exit_spot", "result",
    "contract_id", "balance_after",
]

CYCLE_FIELDS = [
    "ts_utc", "cycle_id", "par", "direction", "resolved_at_level",
    "cycle_result", "net", "balance_after",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_header(path: Path, fields: list[str]) -> None:
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v}"
    return str(v)


def log_level(
    *,
    cycle_id: str,
    par: str,
    iq_symbol: str,
    direction: str,
    level: int,
    stake: Decimal,
    payout_fraction: Decimal,
    entry_spot,
    exit_spot,
    result: str,             # "won" | "lost"
    contract_id,
    balance_after,
) -> None:
    """Una fila por cada nivel ejecutado (entrada/gale1/gale2)."""
    row = {
        "ts_utc": _now_iso(), "cycle_id": cycle_id, "par": par,
        "iq_symbol": iq_symbol, "direction": direction,
        "level": {0: "entrada", 1: "gale1", 2: "gale2"}.get(level, str(level)),
        "stake": stake, "payout_fraction": payout_fraction,
        "entry_spot": entry_spot, "exit_spot": exit_spot, "result": result,
        "contract_id": contract_id, "balance_after": balance_after,
    }
    with _LOCK:
        _ensure_header(config.LEVELS_CSV, LEVEL_FIELDS)
        with config.LEVELS_CSV.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=LEVEL_FIELDS).writerow({k: _to_str(v) for k, v in row.items()})


def log_cycle(
    *,
    cycle_id: str,
    par: str,
    direction: str,
    resolved_at_level: int | None,   # nivel donde se gano; None si se perdio todo
    cycle_result: str,               # "win" | "loss"
    net: Decimal,
    balance_after,
) -> None:
    """Una fila por ciclo cerrado."""
    row = {
        "ts_utc": _now_iso(), "cycle_id": cycle_id, "par": par, "direction": direction,
        "resolved_at_level": (
            {0: "entrada", 1: "gale1", 2: "gale2"}.get(resolved_at_level, "")
            if resolved_at_level is not None else ""
        ),
        "cycle_result": cycle_result, "net": net, "balance_after": balance_after,
    }
    with _LOCK:
        _ensure_header(config.CYCLES_CSV, CYCLE_FIELDS)
        with config.CYCLES_CSV.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CYCLE_FIELDS).writerow({k: _to_str(v) for k, v in row.items()})


def log_error(where: str, exc: BaseException | str) -> None:
    """errors.log: fallos de API, Telegram, parsing, timing. NUNCA tragar errores en silencio (§8, §14)."""
    line = f"{_now_iso()} [{where}] {exc!r}\n" if isinstance(exc, BaseException) else f"{_now_iso()} [{where}] {exc}\n"
    with _LOCK:
        config.ERRORS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with config.ERRORS_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
