"""
gale.py — martingala de META CONSTANTE de Esteban (§4). NO es el x2 del canal.

Para cada nivel n, la apuesta cubre TODO lo perdido antes + la meta del ciclo:

    meta        = INITIAL_STAKE * payout_fraction          # payout REAL leido en vivo de IQ
    apuesta_n   = (perdido_acumulado_antes + meta) / payout_fraction
    apuesta_n   = redondear_al_centavo(apuesta_n)

'payout_fraction' es la fraccion de GANANCIA (ej. 0.87 = +87%), no el payout bruto.
El iqoption_client la lee del payout turbo de IQ (get_all_profit).

Redondeo (config.GALE_ROUNDING):
  - 'ceil'    -> hacia arriba al centavo. Regla §4.1 "nunca quedar corto". Da $2.12 / $4.47.
  - 'nearest' -> al centavo mas cercano. Tabla de referencia §4.2 / §13.4. Da $2.11 / $4.46.
  - 'floor'   -> hacia abajo (no recomendado; puede quedar corto).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal

import config

_CENT = Decimal("0.01")


def round_cent(value: Decimal, mode: str | None = None) -> Decimal:
    """Redondea un monto al centavo segun el modo (default: config.GALE_ROUNDING)."""
    mode = (mode or config.GALE_ROUNDING).lower()
    if mode == "ceil":
        return value.quantize(_CENT, rounding=ROUND_CEILING)
    if mode == "nearest":
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if mode == "floor":
        return value.quantize(_CENT, rounding=ROUND_DOWN)
    raise ValueError(f"modo de redondeo invalido: {mode!r}")


def compute_stake(
    level: int,
    prior_losses: Decimal,
    payout_fraction: Decimal,
    initial_stake: Decimal | None = None,
    rounding: str | None = None,
) -> Decimal:
    """
    Apuesta para 'level' (0=entrada, 1=Gale1, 2=Gale2).

    'prior_losses' = suma de stakes perdidos en los niveles anteriores de ESTE ciclo.
    'payout_fraction' = fraccion de ganancia del contrato de ESTE nivel (leida en vivo).

    Nota: en level 0, (0 + meta)/payout == initial_stake exactamente, asi que la entrada
    siempre vale INITIAL_STAKE sin caso especial (siempre que payout > 0).
    """
    if initial_stake is None:
        initial_stake = config.INITIAL_STAKE
    if payout_fraction <= 0:
        raise ValueError(f"payout_fraction debe ser > 0, es {payout_fraction}")
    if prior_losses < 0:
        raise ValueError("prior_losses no puede ser negativo")

    meta = initial_stake * payout_fraction
    raw = (prior_losses + meta) / payout_fraction
    return round_cent(raw, rounding)


@dataclass(frozen=True)
class CyclePlan:
    """Plan completo del ciclo precomputado con un payout fijo (para previsualizar/auditar)."""
    stakes: list[Decimal]       # [entrada, gale1, gale2]
    meta: Decimal               # ganancia objetivo del ciclo
    worst_case_loss: Decimal    # perdida si se pierden los 3 niveles (suma de stakes)

    def net_if_win_at(self, level: int, payout_fraction: Decimal) -> Decimal:
        """Neto del ciclo si se gana exactamente en 'level'."""
        prior = sum(self.stakes[:level], Decimal("0"))
        return self.stakes[level] * payout_fraction - prior


def plan_cycle(
    payout_fraction: Decimal,
    initial_stake: Decimal | None = None,
    rounding: str | None = None,
    max_gale_levels: int | None = None,
) -> CyclePlan:
    """
    Precomputa los stakes de los 3 niveles con un payout FIJO (referencia/auditoria).
    En vivo el bot recalcula cada nivel con el payout real de su propia proposal (§4.3).
    """
    if initial_stake is None:
        initial_stake = config.INITIAL_STAKE
    if max_gale_levels is None:
        max_gale_levels = config.MAX_GALE_LEVELS

    stakes: list[Decimal] = []
    prior = Decimal("0")
    for level in range(max_gale_levels + 1):
        s = compute_stake(level, prior, payout_fraction, initial_stake, rounding)
        stakes.append(s)
        prior += s  # si pierde este nivel, se acumula a lo perdido

    return CyclePlan(
        stakes=stakes,
        meta=initial_stake * payout_fraction,
        worst_case_loss=sum(stakes, Decimal("0")),
    )
