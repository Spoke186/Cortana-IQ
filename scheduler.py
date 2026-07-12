"""
scheduler.py — convierte la hora de la senal (UTC-3) a UTC y calcula las horas de
ejecucion de cada nivel: entrada, Gale 1 (+5), Gale 2 (+10).  (§2, §3)

REGLA CRITICA (§2): la hora de la senal SIEMPRE se interpreta en SIGNAL_TIMEZONE,
nunca en la hora local de la maquina. Todo se programa contra UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
from parser import Signal


@dataclass(frozen=True)
class Schedule:
    """Resultado de programar una senal."""
    skipped: bool
    reason: str                     # "" si no se salta; motivo si skipped
    # Horas de ejecucion en UTC, indexadas por nivel: [0]=entrada, [1]=gale1, [2]=gale2
    run_times_utc: list[datetime]
    entry_local_signal: datetime    # hora de entrada en la TZ de la senal (para mostrar)
    entry_local_display: datetime   # hora de entrada en la TZ de Esteban (para mostrar)
    gale_mismatch: bool = False     # True si las horas declaradas no cuadran con las derivadas


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def build_schedule(
    signal: Signal,
    now_utc: datetime | None = None,
    *,
    tz: str | None = None,
    max_levels: int | None = None,
    step_minutes: int | None = None,
) -> Schedule:
    """
    Calcula las horas UTC de entrada y de los Gale.

    Multicanal (2026-07-11): tz/max_levels/step por PROVEEDOR. Defaults = config (canal 'main').
      - tz          : zona horaria de la HORA de la senal del proveedor.
      - max_levels  : niveles de Gale (0 = sin martingala -> solo entrada).
      - step_minutes: separacion entre niveles = expiracion del contrato (M1->1, M5->5).
                      Default: signal.duration_min (M1/M5) o config.GALE_STEP_MINUTES.

    Cruce de medianoche (§2): los Gale se calculan con timedelta sobre el datetime
    aware, asi que rolar al dia siguiente es automatico y correcto.

    Senal vencida vs senal de manana (§2):
      - Si la entrada de HOY (en TZ de la senal) ya paso, pero por POCO
        (<= STALE_SIGNAL_HOURS), se considera VENCIDA -> skip.
      - Si paso por MUCHO (> STALE_SIGNAL_HOURS), se asume que la HH:MM es de manana
        (caso tipico: senal 00:05 recibida a las 23:59) -> rola +1 dia.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        raise ValueError("now_utc debe ser timezone-aware (UTC)")

    if tz is None:
        tz = config.SIGNAL_TIMEZONE
    if max_levels is None:
        max_levels = config.MAX_GALE_LEVELS
    if step_minutes is None:
        step_minutes = getattr(signal, "duration_min", None) or config.GALE_STEP_MINUTES

    sig_tz = ZoneInfo(tz)
    disp_tz = ZoneInfo(config.DISPLAY_TIMEZONE)

    now_sig = now_utc.astimezone(sig_tz)
    hh, mm = _parse_hhmm(signal.entry_hhmm)

    entry_date = getattr(signal, "entry_date", None)
    if entry_date:
        # LISTA DIARIA con fecha en el header: agendar en esa fecha EXACTA. Si ya paso -> vencida
        # (NO rodar al futuro; asi las listas de dias anteriores se saltan enteras). (multicanal)
        y, mo, d = (int(x) for x in entry_date.split("-"))
        entry_sig = datetime(y, mo, d, hh, mm, tzinfo=sig_tz)
        if entry_sig <= now_sig:
            return Schedule(
                skipped=True,
                reason=f"senal vencida (lista {entry_date} {signal.entry_hhmm} ya paso)",
                run_times_utc=[],
                entry_local_signal=entry_sig,
                entry_local_display=entry_sig.astimezone(disp_tz),
            )
    else:
        # Canal en vivo 'main' (sin fecha): heuristica hoy/manana (§2).
        entry_sig = now_sig.replace(hour=hh, minute=mm, second=0, microsecond=0)
        stale_window = timedelta(hours=config.STALE_SIGNAL_HOURS)
        if entry_sig <= now_sig:
            past_by = now_sig - entry_sig
            if past_by > stale_window:
                # Muy en el pasado -> es la HH:MM de manana.
                entry_sig = entry_sig + timedelta(days=1)
            else:
                # Paso hace poco -> senal vencida, no operar (§2).
                return Schedule(
                    skipped=True,
                    reason=f"senal vencida (entrada {signal.entry_hhmm} ya paso hace {past_by})",
                    run_times_utc=[],
                    entry_local_signal=entry_sig,
                    entry_local_display=entry_sig.astimezone(disp_tz),
                )

    # Horas de ejecucion: entrada, +step, +2*step (sobre datetime aware -> cruce de medianoche ok).
    run_times_utc: list[datetime] = []
    for level in range(max_levels + 1):
        t_sig = entry_sig + timedelta(minutes=step_minutes * level)
        run_times_utc.append(t_sig.astimezone(timezone.utc))

    # Cruce con las horas de Gale declaradas por el canal (§1.4): warn pero usar las derivadas.
    gale_mismatch = _check_declared_gales(signal, entry_sig)

    return Schedule(
        skipped=False,
        reason="",
        run_times_utc=run_times_utc,
        entry_local_signal=entry_sig,
        entry_local_display=entry_sig.astimezone(disp_tz),
        gale_mismatch=gale_mismatch,
    )


def _check_declared_gales(signal: Signal, entry_sig: datetime) -> bool:
    """
    Compara las HH:MM derivadas (entrada+5, +10) con las 'TIEMPO HASTA HH:MM' del canal.
    El canal suele declarar: cierre(+5), gale1(+5 desde cierre=+10... varia). Solo chequeamos
    que el set de horas derivadas este contenido en lo declarado; si no, marcamos mismatch.
    Devuelve True si hay discrepancia (el caller loguea warning y usa las derivadas).
    """
    if not signal.declared_gale_hhmm:
        return False
    derived = {
        (entry_sig + timedelta(minutes=config.GALE_STEP_MINUTES * lvl)).strftime("%H:%M")
        for lvl in (1, 2)
    }
    declared = set(signal.declared_gale_hhmm)
    return not derived.issubset(declared)


def seconds_until(target_utc: datetime, now_utc: datetime | None = None) -> float:
    """Segundos desde ahora hasta target_utc (negativo si ya paso)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return (target_utc - now_utc).total_seconds()
