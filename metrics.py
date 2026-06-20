"""
metrics.py — reporte del WR CRUDO real (§9, §14).

El numero que importa NO es el del canal (que cuenta los Gale como wins), sino el
WR CRUDO por entrada = (entradas directas ganadas) / (total entradas).

Uso:
    python metrics.py            # lee logs/levels.csv y logs/cycles.csv
"""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import config


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def report() -> str:
    levels = _read(config.LEVELS_CSV)
    cycles = _read(config.CYCLES_CSV)

    # --- WR CRUDO por entrada (solo nivel 'entrada') ---
    entradas = [r for r in levels if r.get("level") == "entrada"]
    entradas_total = len(entradas)
    entradas_won = sum(1 for r in entradas if r.get("result") == "won")
    wr_crudo = (entradas_won / entradas_total) if entradas_total else 0.0

    # --- WR por ciclo ---
    cyc_total = len(cycles)
    cyc_win = sum(1 for r in cycles if r.get("cycle_result") == "win")
    wr_ciclo = (cyc_win / cyc_total) if cyc_total else 0.0

    # --- Distribucion: donde se resolvio cada ciclo ---
    dist = {"entrada": 0, "gale1": 0, "gale2": 0, "perdido": 0}
    for r in cycles:
        if r.get("cycle_result") == "win":
            dist[r.get("resolved_at_level") or "entrada"] = dist.get(r.get("resolved_at_level") or "entrada", 0) + 1
        elif r.get("cycle_result") == "loss":
            dist["perdido"] += 1

    # --- Neto acumulado + drawdown ---
    cum = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for r in cycles:
        net_raw = r.get("net") or "0"
        try:
            cum += Decimal(net_raw)
        except Exception:  # noqa: BLE001
            continue
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # Break-even teorico (§14): con payout p, WR crudo break-even ~ 1/(1+p). Con p=0.90 -> ~52.6%.
    p = Decimal("0.90")
    be = 1 / (1 + p)

    lines = [
        "===== REPORTE WR (crudo, auditable) =====",
        f"Entradas totales        : {entradas_total}",
        f"Entradas ganadas        : {entradas_won}",
        f"WR CRUDO por entrada    : {wr_crudo:.4f}  ({wr_crudo*100:.2f}%)   <-- EL NUMERO QUE IMPORTA",
        f"Break-even (payout 0.90): {float(be):.4f}  ({float(be)*100:.2f}%)",
        "",
        f"Ciclos totales          : {cyc_total}",
        f"Ciclos ganados          : {cyc_win}",
        f"WR por ciclo            : {wr_ciclo:.4f}  ({wr_ciclo*100:.2f}%)",
        "",
        "Distribucion de resolucion del ciclo:",
        f"  en Entrada : {dist['entrada']}",
        f"  en Gale 1  : {dist['gale1']}",
        f"  en Gale 2  : {dist['gale2']}",
        f"  perdido    : {dist['perdido']}",
        "",
        f"Neto acumulado          : ${cum}",
        f"Max drawdown            : ${max_dd}",
        "=========================================",
    ]
    if entradas_total and wr_crudo < float(be):
        lines.append("⚠️  WR crudo POR DEBAJO del break-even: el sistema es EV-negativo a este payout.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
