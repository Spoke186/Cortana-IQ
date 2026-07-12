# -*- coding: utf-8 -*-
"""mc_stake.py — Monte Carlo bootstrap de combinaciones de stake (handoff 2026-06-23).

Barre grid de stakes x gale_max en 2 escenarios (A=todo, B=subset +EV), sobre IS(2025) y
OOS(2026). Bootstrap (resample con reemplazo) de la secuencia de ciclos. Reporta DISTRIBUCION
(p5/p50/p95), prob_ruina, max_drawdown, EV/ciclo analitico. OOS = mismas params, sin re-optimizar.

Decisiones de diseno (confirmadas con Esteban):
  - WIN_GALE no trae nivel -> modelo coin-flip P(gale1|WG)=1/(2-p), p=1-cbrt(lossP) por periodo.
    Nivel se sortea por draw (latente).
  - payout_fraction FIJO = 0.87. Redondeo Gale = ceil (igual produccion).
  - capital inicial 650. N=10000 paths. Largo path = nro ciclos operables del escenario/periodo.
"""
import json, re, csv, sys, collections
from datetime import datetime, timezone
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

# ---------------- parametros ----------------
CAPITAL0   = 650.0
PAYOUT     = 0.87
N_PATHS    = 10000
BATCH      = 2000
BASE_SEED  = 12345
SUBSET     = {"AUD/JPY", "AUD/CAD", "EUR/USD", "CAD/CHF", "CHF/JPY"}
HIGH_PAIRS = {"AUD/JPY", "AUD/CAD"}            # reciben stake_alto
STAKE_ALTO = [5, 8, 12]
STAKE_EST  = [1, 2, 3]
GALE_MAX   = [0, 1]
MAJORS = {"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD"}

# ---------------- parse historico ----------------
SIG = re.compile(r"(?P<par>[A-Z]{3}/[A-Z]{3})\s*;\s*(?P<hora>\d{2}:\d{2})\s*;\s*(?P<dir>(?i:PUT|CALL))")
def is_sig(t):
    m = SIG.search(t or "")
    if not m: return None
    if re.match(r"\s*(?:-+>|—+>|→)", t[m.end():m.end()+6]): return None
    hh, mm = (int(x) for x in m.group("hora").split(":"))
    return m.group("par").upper() if 0 <= hh <= 23 and 0 <= mm <= 59 else None
def nat(p):
    a, b = p.split("/"); return "REAL" if a in MAJORS and b in MAJORS else "OTC"
def cls(t):
    if not t: return None
    f = t.strip().splitlines()[0]; u = f.upper()
    if "WIN" in u and "DIRECTO" in u: return "WD"
    if "WIN" in u and "GALE" in u: return "WG"
    if f.strip().startswith("❌") and ("ANALISIS" in u or "ANÁLISIS" in u or "SEGUIMOS OPERANDO" in u or u.strip()=="❌ PERSONAL."): return "L"
    return None

def build_cycles(path):
    d = json.load(open(path, encoding="utf-8")); d.sort(key=lambda m: m["id"])
    out = []; pend = None
    for m in d:
        t = m.get("text") or ""; dt = datetime.fromisoformat(m["date"]).astimezone(timezone.utc)
        p = is_sig(t)
        if p: pend = (p, dt); continue
        r = cls(t)
        if r and pend:
            out.append((pend[0], nat(pend[0]), r, pend[1])); pend = None
    return [c for c in out if (c[3].year, c[3].month) >= (2025, 2)]   # desde feb-2025

OUT_CODE = {"WD": 0, "WG": 1, "L": 2}

def make_pool(cycles, scenario):
    """Devuelve (out_codes, is_high) para los ciclos operables del escenario."""
    if scenario == "B":
        cyc = [c for c in cycles if c[0] in SUBSET]
    else:
        cyc = cycles
    out  = np.array([OUT_CODE[c[2]] for c in cyc], dtype=np.int8)
    high = np.array([c[0] in HIGH_PAIRS for c in cyc], dtype=bool)
    return out, high

def pg1_for(out_codes):
    """P(gale1|WG) = 1/(2-p), p=1-cbrt(lossP)."""
    lossP = (out_codes == 2).mean()
    p = 1 - lossP ** (1/3)
    return 1.0 / (2 - p), lossP, p

def stakes_for(is_high, s_alto, s_est):
    s0 = np.where(is_high, float(s_alto), float(s_est))
    s1 = np.ceil(s0 * (1 + PAYOUT) / PAYOUT * 100) / 100   # ceil al centavo
    return s0, s1

def analytic_ev(out_codes, s0, s1, G, pg1):
    """EV $/ciclo analitico (sin ruina), promediado sobre el pool."""
    f = PAYOUT; pg2 = 1 - pg1
    net = np.empty(len(out_codes))
    wd = out_codes == 0; wg = out_codes == 1; l = out_codes == 2
    net[wd] = s0[wd] * f
    if G == 0:
        net[wg] = -s0[wg]
        net[l]  = -s0[l]
    else:
        net[wg] = pg1 * (s1[wg]*f - s0[wg]) + pg2 * (-(s0[wg]+s1[wg]))
        net[l]  = -(s0[l] + s1[l])
    return net.mean()

def simulate(out_codes, is_high, s_alto, s_est, G, pg1, seed, n=N_PATHS):
    """Bootstrap n paths. Devuelve dict de metricas + array de capital final."""
    rng = np.random.default_rng(seed)
    L = len(out_codes)
    s0_pool, s1_pool = stakes_for(is_high, s_alto, s_est)
    f = PAYOUT
    finals = np.empty(n); mdds = np.empty(n); ruined = np.zeros(n, dtype=bool)
    done = 0
    while done < n:
        b = min(BATCH, n - done)
        idx = rng.integers(0, L, size=(b, L))
        out_d = out_codes[idx]
        s0_d  = s0_pool[idx]
        s1_d  = s1_pool[idx]
        net = np.empty((b, L))
        wd = out_d == 0; wg = out_d == 1; lo = out_d == 2
        net[wd] = s0_d[wd] * f
        if G == 0:
            net[wg] = -s0_d[wg]
            net[lo] = -s0_d[lo]
        else:
            # WG: sortear nivel por draw
            u = rng.random((b, L))
            win_g1 = wg & (u < pg1)
            net[wg] = -(s0_d[wg] + s1_d[wg])                 # default: perdio gale2
            net[win_g1] = (s1_d * f - s0_d)[win_g1]          # gano gale1
            net[lo] = -(s0_d[lo] + s1_d[lo])
        cum = np.cumsum(net, axis=1)
        cap_after = CAPITAL0 + cum
        pre_cap = cap_after - net                            # capital antes de cada ciclo
        ruin_mask = pre_cap < s0_d                           # no alcanza para la entrada
        is_ruined = ruin_mask.any(axis=1)
        first = ruin_mask.argmax(axis=1)
        rows = np.arange(b)
        pre_at_first = pre_cap[rows, first]
        col = np.arange(L)
        frozen = col[None, :] >= first[:, None]
        eff = np.where(is_ruined[:, None] & frozen, pre_at_first[:, None], cap_after)
        curve = np.concatenate([np.full((b, 1), CAPITAL0), eff], axis=1)
        peak = np.maximum.accumulate(curve, axis=1)
        mdd = (peak - curve).max(axis=1)
        final = np.where(is_ruined, pre_at_first, cap_after[:, -1])
        finals[done:done+b] = final; mdds[done:done+b] = mdd; ruined[done:done+b] = is_ruined
        done += b
    ev = analytic_ev(out_codes, s0_pool, s1_pool, G, pg1)
    return {
        "path_len": L, "seed": seed, "ev_ciclo": ev,
        "cap_p5": np.percentile(finals, 5), "cap_p50": np.percentile(finals, 50),
        "cap_p95": np.percentile(finals, 95), "prob_ruina": ruined.mean(),
        "mdd_p50": np.percentile(mdds, 50), "mdd_p95": np.percentile(mdds, 95),
    }, finals

# ---------------- correr grid ----------------
def main():
    cycles = build_cycles("history_dump_full.json")
    IS  = [c for c in cycles if c[3].year == 2025]
    OOS = [c for c in cycles if c[3].year == 2026]
    print(f"ciclos feb25+: {len(cycles)}  | IS(2025)={len(IS)}  OOS(2026)={len(OOS)}")

    runs = []; finals_store = {}
    seed = BASE_SEED
    for scen in ("A", "B"):
        for period, data in (("IS", IS), ("OOS", OOS)):
            out_codes, is_high = make_pool(data, scen)
            pg1, lossP, p = pg1_for(out_codes)
            for sa in STAKE_ALTO:
                for se in STAKE_EST:
                    for G in GALE_MAX:
                        seed += 1
                        met, finals = simulate(out_codes, is_high, sa, se, G, pg1, seed)
                        key = (scen, period, sa, se, G)
                        met.update({"scenario": scen, "period": period, "stake_alto": sa,
                                    "stake_est": se, "gale_max": G, "pg1": round(pg1, 3),
                                    "lossP": round(float(lossP), 3)})
                        runs.append(met); finals_store[key] = finals
            print(f"  {scen}/{period}: pool={len(out_codes)} pg1={pg1:.3f} lossP={lossP:.3f}  (18 combos)")

    # CSV
    cols = ["scenario","period","stake_alto","stake_est","gale_max","path_len","ev_ciclo",
            "cap_p5","cap_p50","cap_p95","prob_ruina","mdd_p50","mdd_p95","pg1","lossP","seed"]
    with open("mc_results.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for r in runs:
            w.writerow({k: (f"{r[k]:.4f}" if isinstance(r[k], float) else r[k]) for k in cols})
    print(f"\nCSV -> mc_results.csv ({len(runs)} filas)")

    np.save("mc_finals.npy", np.array([], dtype=object))  # placeholder; finals_store usado en plot
    import pickle
    pickle.dump(finals_store, open("mc_finals.pkl", "wb"))
    pickle.dump(runs, open("mc_runs.pkl", "wb"))
    return runs

if __name__ == "__main__":
    import time
    t0 = time.time()
    main()
    print(f"tiempo: {time.time()-t0:.1f}s")
