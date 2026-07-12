# -*- coding: utf-8 -*-
"""report_mc.py — reporte IS-vs-OOS de las candidatas + chart comparativo A vs B."""
import pickle, sys
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")

runs = pickle.load(open("mc_runs.pkl", "rb"))
finals = pickle.load(open("mc_finals.pkl", "rb"))
CAP0 = 650

def get(scen, period, sa, se, G):
    for r in runs:
        if (r["scenario"],r["period"],r["stake_alto"],r["stake_est"],r["gale_max"])==(scen,period,sa,se,G):
            return r
    return None

def key(r): return (r["stake_alto"], r["stake_est"], r["gale_max"])

def topN(scen, period, by, n=3):
    rs=[r for r in runs if r["scenario"]==scen and r["period"]==period]
    if by=="return": rs=sorted(rs,key=lambda x:-x["cap_p50"])
    else: rs=sorted(rs,key=lambda x:(x["prob_ruina"],-x["cap_p5"]))   # supervivencia
    return rs[:n]

def line(r):
    return (f"alto{r['stake_alto']:>3} est{r['stake_est']:>2} G{r['gale_max']} | "
            f"EV{r['ev_ciclo']:+.3f} p5={r['cap_p5']:>4.0f} p50={r['cap_p50']:>4.0f} "
            f"p95={r['cap_p95']:>5.0f} ruina={100*r['prob_ruina']:>4.1f}% mddP95={r['mdd_p95']:>4.0f}")

print("="*78)
print("MONTE CARLO STAKE — REPORTE  (cap inicial $650, N=10000, payout 0.87, IS=2025 OOS=2026)")
print("="*78)

for scen,name in (("A","EJECUTAR TODO"),("B","SUBSET +EV (5 pares REAL)")):
    print(f"\n########## ESCENARIO {scen} — {name} ##########")
    cand = []
    for by in ("return","survival"):
        for r in topN(scen,"IS",by):
            if key(r) not in [key(c) for c in cand]: cand.append(r)
    print(f"  Candidatas (top-IS por retorno + por supervivencia), re-evaluadas en OOS:\n")
    print(f"  {'COMBO':>16}   IS  -> OOS")
    for c in cand:
        o = get(scen,"OOS",*key(c))
        is_ev = c["ev_ciclo"]; oos_ev = o["ev_ciclo"]
        robust = "ROBUSTA ✅" if (is_ev>0 and oos_ev>0) else ("COLAPSA OOS ❌" if is_ev>0 and oos_ev<=0 else "—")
        print(f"  IS : {line(c)}")
        print(f"  OOS: {line(o)}   [{robust}]")
        print()

# ---- respuestas de texto ----
print("="*78); print("RESPUESTAS"); print("="*78)
A_is_pos = [r for r in runs if r["scenario"]=="A" and r["period"]=="IS" and r["ev_ciclo"]>0]
A_oos_pos= [r for r in runs if r["scenario"]=="A" and r["period"]=="OOS" and r["ev_ciclo"]>0]
print(f"\n1) Combinaciones de A (todo) con EV+:  IS={len(A_is_pos)}  OOS={len(A_oos_pos)}  -> el canal completo es -EV (esperado).")

bestA = sorted([r for r in runs if r['scenario']=='A' and r['period']=='OOS'],key=lambda x:-x['cap_p50'])[0]
bestB = sorted([r for r in runs if r['scenario']=='B' and r['period']=='OOS'],key=lambda x:-x['cap_p50'])[0]
print(f"\n2) Mejor A (OOS) p50=${bestA['cap_p50']:.0f} (EV{bestA['ev_ciclo']:+.3f})  vs  mejor B (OOS) p50=${bestB['cap_p50']:.0f} (EV{bestB['ev_ciclo']:+.3f}).")
print(f"   B mediana ${bestB['cap_p50']-CAP0:+.0f} vs A ${bestA['cap_p50']-CAP0:+.0f} sobre el capital inicial.")

# robustez: B combos +EV en ambos
b_robust=[r for r in runs if r['scenario']=='B' and r['period']=='IS' and r['ev_ciclo']>0
          and get('B','OOS',*key(r))['ev_ciclo']>0]
b_collapse=[r for r in runs if r['scenario']=='B' and r['period']=='IS' and r['ev_ciclo']>0
            and get('B','OOS',*key(r))['ev_ciclo']<=0]
print(f"\n3) B: combos +EV en IS={len([r for r in runs if r['scenario']=='B' and r['period']=='IS' and r['ev_ciclo']>0])}.")
print(f"   De esos, ROBUSTOS (+EV tambien OOS)={len(b_robust)}, COLAPSAN OOS={len(b_collapse)}.")
if b_collapse:
    parts = ["alto{}/est{}/G{}".format(r["stake_alto"], r["stake_est"], r["gale_max"]) for r in b_collapse]
    print("   Colapsan (overfit): " + ", ".join(parts))
print(f"   Patron: en B los G=1 aguantan OOS; varios G=0 colapsan (subset OOS lossP=0.08 premia la recuperacion).")

# ---- chart ----
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig=plt.figure(figsize=(15,9)); fig.suptitle("Monte Carlo stake — A (todo) vs B (subset +EV)  | cap $650",fontsize=14,weight="bold")

# P1: distribucion capital final, mejores de cada uno, IS y OOS
ax=fig.add_subplot(2,2,1)
sets=[("A IS",finals[("A","IS",*key(sorted([r for r in runs if r['scenario']=='A'and r['period']=='IS'],key=lambda x:-x['cap_p50'])[0]))]),
      ("A OOS",finals[("A","OOS",*key(bestA))]),
      ("B IS",finals[("B","IS",*key(sorted([r for r in runs if r['scenario']=='B'and r['period']=='IS'],key=lambda x:-x['cap_p50'])[0]))]),
      ("B OOS",finals[("B","OOS",*key(bestB))])]
ax.boxplot([s[1] for s in sets],tick_labels=[s[0] for s in sets],showfliers=False,whis=[5,95])
ax.axhline(CAP0,color="red",ls="--",lw=1); ax.text(0.6,CAP0,"inicial 650",color="red",fontsize=8)
ax.set_title("Capital final (caja=IQR, bigote=p5-p95)\nmejor combo por retorno de cada celda"); ax.set_ylabel("$")

# P2: EV/ciclo todas las combos, A vs B, IS y OOS
ax=fig.add_subplot(2,2,2)
for scen,col in (("A","#c62828"),("B","#2e7d32")):
    for per,mk in (("IS","o"),("OOS","s")):
        ev=[r["ev_ciclo"] for r in runs if r["scenario"]==scen and r["period"]==per]
        ax.scatter([f"{scen}-{per}"]*len(ev),ev,c=col,marker=mk,alpha=0.6,s=30)
ax.axhline(0,color="k",lw=1); ax.set_title("EV $/ciclo (todas las 18 combos por celda)"); ax.set_ylabel("EV $/ciclo")

# P3: prob_ruina vs p50 (todas), color por escenario, OOS
ax=fig.add_subplot(2,2,3)
for scen,col in (("A","#c62828"),("B","#2e7d32")):
    rs=[r for r in runs if r["scenario"]==scen and r["period"]=="OOS"]
    ax.scatter([100*r["prob_ruina"] for r in rs],[r["cap_p50"] for r in rs],c=col,label=scen,alpha=0.7,s=40)
ax.axhline(CAP0,color="red",ls="--",lw=1)
ax.set_xlabel("prob ruina %"); ax.set_ylabel("capital p50 $"); ax.set_title("OOS: riesgo (ruina) vs retorno (p50)"); ax.legend()

# P4: texto resumen
ax=fig.add_subplot(2,2,4); ax.axis("off")
bb=sorted([r for r in runs if r['scenario']=='B'and r['period']=='OOS'],key=lambda x:-x['cap_p50'])[0]
bsurv=sorted([r for r in runs if r['scenario']=='B'and r['period']=='OOS'],key=lambda x:(x['prob_ruina'],-x['cap_p5']))[0]
txt=("CONCLUSIONES\n────────────────────────\n"
 f"A (todo): -EV en IS y OOS, sin excepcion.\n"
 f"   mejor A OOS: p50 ${bestA['cap_p50']:.0f} (pierde ${CAP0-bestA['cap_p50']:.0f}).\n\n"
 f"B (subset 5 REAL): +EV robusto con G=1.\n"
 f"   B OOS mejor retorno: alto{bb['stake_alto']}/est{bb['stake_est']}/G{bb['gale_max']}\n"
 f"      p50 ${bb['cap_p50']:.0f}  p5 ${bb['cap_p5']:.0f}  ruina {100*bb['prob_ruina']:.1f}%\n"
 f"   B OOS mejor supervivencia: alto{bsurv['stake_alto']}/est{bsurv['stake_est']}/G{bsurv['gale_max']}\n"
 f"      p50 ${bsurv['cap_p50']:.0f}  p5 ${bsurv['cap_p5']:.0f}  ruina {100*bsurv['prob_ruina']:.1f}%\n\n"
 f"Robustas B (+EV IS y OOS): {len(b_robust)}\n"
 f"Colapsan OOS (overfit): {len(b_collapse)}\n"
 "────────────────────────\n"
 "Stake alto >$12 NO barrido (regla).\n"
 "WG nivel: modelo 68/32. Payout 0.87.")
ax.text(0,0.98,txt,va="top",fontsize=10,family="monospace")

fig.tight_layout(rect=[0,0,1,0.96]); fig.savefig("mc_compare.png",dpi=110)
print("\nPNG -> mc_compare.png")
