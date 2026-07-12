"""
Tests de la formula de Gale meta-constante (§4, §13.4).

Discrepancia documentada en el spec:
  - §4.1 dice "redondear hacia ARRIBA al centavo" (nunca quedar corto)  -> ceil: 2.12 / 4.47 / -7.59
  - §4.2 tabla + §13.4 valores esperados                                -> nearest: 2.11 / 4.46 / -7.57
Aqui se verifican AMBOS modos explicitamente. El default del bot es 'ceil' (config.GALE_ROUNDING).
"""
from decimal import Decimal

import pytest

from gale import compute_stake, plan_cycle, round_cent

PAYOUT = Decimal("0.90")
INIT = Decimal("1.00")


def test_entrada_siempre_initial_stake():
    # (0 + meta)/payout == initial_stake, en cualquier modo y cualquier payout.
    for mode in ("ceil", "nearest", "floor"):
        s = compute_stake(0, Decimal("0"), PAYOUT, INIT, rounding=mode)
        assert s == Decimal("1.00"), mode
    # payout distinto, entrada sigue siendo el stake inicial:
    assert compute_stake(0, Decimal("0"), Decimal("0.85"), INIT) == Decimal("1.00")


def test_ceil_valores():
    # max_gale_levels=2 explicito: valida la formula a 3 niveles aunque produccion opere 1.
    plan = plan_cycle(PAYOUT, INIT, rounding="ceil", max_gale_levels=2)
    assert plan.stakes == [Decimal("1.00"), Decimal("2.12"), Decimal("4.47")]
    assert plan.worst_case_loss == Decimal("7.59")


def test_nearest_valores_tabla_referencia():
    # Reproduce la tabla §4.2 / §13.4 del documento (3 niveles, formula).
    plan = plan_cycle(PAYOUT, INIT, rounding="nearest", max_gale_levels=2)
    assert plan.stakes == [Decimal("1.00"), Decimal("2.11"), Decimal("4.46")]
    assert plan.worst_case_loss == Decimal("7.57")


def test_ceil_nunca_queda_corto():
    # En modo ceil, ganar en cualquier nivel deja neto >= meta (regla §4.1).
    plan = plan_cycle(PAYOUT, INIT, rounding="ceil")
    for level in range(len(plan.stakes)):
        net = plan.net_if_win_at(level, PAYOUT)
        assert net >= plan.meta, f"nivel {level} quedo corto: {net} < {plan.meta}"


def test_meta_es_initial_por_payout():
    plan = plan_cycle(PAYOUT, INIT)
    assert plan.meta == Decimal("0.90")


def test_round_cent_modos():
    assert round_cent(Decimal("2.1111"), "ceil") == Decimal("2.12")
    assert round_cent(Decimal("2.1111"), "nearest") == Decimal("2.11")
    assert round_cent(Decimal("2.1111"), "floor") == Decimal("2.11")
    assert round_cent(Decimal("4.4555"), "nearest") == Decimal("4.46")


def test_payout_invalido():
    with pytest.raises(ValueError):
        compute_stake(1, Decimal("1.00"), Decimal("0"), INIT)


def test_prior_losses_negativo():
    with pytest.raises(ValueError):
        compute_stake(1, Decimal("-1"), PAYOUT, INIT)


def test_payout_real_distinto_recalcula():
    # Si el payout del Gale baja a 0.80, la apuesta sube (cubre lo perdido + meta con peor payout).
    # prior=1.00, meta=1.00*0.80=0.80 -> raw=(1.00+0.80)/0.80=2.25 -> ceil 2.25
    s = compute_stake(1, Decimal("1.00"), Decimal("0.80"), INIT, rounding="ceil")
    assert s == Decimal("2.25")
