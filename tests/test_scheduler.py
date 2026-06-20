"""Tests del scheduler (§2, §3, §13.3): conversion UTC-3 -> UTC, +5/+10, cruce de medianoche."""
from datetime import datetime, timezone

from parser import Signal
from scheduler import build_schedule

UTC = timezone.utc


def _sig(hhmm: str, direction: str = "PUT", par: str = "EUR/USD") -> Signal:
    return Signal(par=par, entry_hhmm=hhmm, direction=direction)


def test_conversion_utc3_a_utc():
    # Sao Paulo es UTC-3 (sin DST). 00:45 local -> 03:45 UTC.
    now = datetime(2026, 6, 19, 3, 0, tzinfo=UTC)  # = 00:00 en Sao Paulo
    sched = build_schedule(_sig("00:45"), now_utc=now)
    assert not sched.skipped
    assert sched.run_times_utc[0] == datetime(2026, 6, 19, 3, 45, tzinfo=UTC)


def test_gale_times_mas_5_y_10():
    now = datetime(2026, 6, 19, 3, 0, tzinfo=UTC)
    sched = build_schedule(_sig("00:45"), now_utc=now)
    assert sched.run_times_utc[1] == datetime(2026, 6, 19, 3, 50, tzinfo=UTC)  # +5
    assert sched.run_times_utc[2] == datetime(2026, 6, 19, 3, 55, tzinfo=UTC)  # +10


def test_cruce_de_medianoche():
    # now = 23:50 en Sao Paulo (2026-06-19). Senal 23:58 -> entrada 02:58 UTC del dia 20.
    # Gale1 (00:03 local del 20) -> 03:03 UTC; Gale2 (00:08) -> 03:08 UTC.
    now = datetime(2026, 6, 20, 2, 50, tzinfo=UTC)  # = 2026-06-19 23:50 Sao Paulo
    sched = build_schedule(_sig("23:58"), now_utc=now)
    assert not sched.skipped
    assert sched.run_times_utc[0] == datetime(2026, 6, 20, 2, 58, tzinfo=UTC)
    assert sched.run_times_utc[1] == datetime(2026, 6, 20, 3, 3, tzinfo=UTC)
    assert sched.run_times_utc[2] == datetime(2026, 6, 20, 3, 8, tzinfo=UTC)


def test_senal_vencida_se_salta():
    # now = 00:50 Sao Paulo, senal 00:45 (paso hace 5 min, dentro de la ventana stale) -> vencida.
    now = datetime(2026, 6, 19, 3, 50, tzinfo=UTC)  # = 00:50 Sao Paulo
    sched = build_schedule(_sig("00:45"), now_utc=now)
    assert sched.skipped
    assert "vencida" in sched.reason


def test_senal_de_manana_rola_un_dia():
    # now = 23:59 Sao Paulo (19). Senal 00:05: hoy ya paso por ~24h (>12h) -> es del dia 20.
    now = datetime(2026, 6, 20, 2, 59, tzinfo=UTC)  # = 2026-06-19 23:59 Sao Paulo
    sched = build_schedule(_sig("00:05"), now_utc=now)
    assert not sched.skipped
    # 00:05 del 2026-06-20 en Sao Paulo -> 03:05 UTC del mismo dia.
    assert sched.run_times_utc[0] == datetime(2026, 6, 20, 3, 5, tzinfo=UTC)


def test_now_naive_falla():
    import pytest

    with pytest.raises(ValueError):
        build_schedule(_sig("00:45"), now_utc=datetime(2026, 6, 19, 3, 0))
