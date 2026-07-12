# -*- coding: utf-8 -*-
"""plot_2026.py — distribuciones estadisticas 2026 en PNG (4 paneles)."""
import json, re, collections
from datetime import datetime, timezone
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SIGNAL_RE = re.compile(r"(?P<par>[A-Z]{3}/[A-Z]{3})\s*;\s*(?P<hora>\d{2}:\d{2})\s*;\s*(?P<dir>(?i:PUT|CALL))")
MAJORS = {"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD"}
def is_signal(t):
    m=SIGNAL_RE.search(t or "")
    if not m: return None
    tail=t[m.end():m.end()+6]
    if re.match(r"\s*(?:-+>|—+>|→)",tail): return None
    hh,mm=(int(x) for x in m.group("hora").split(":"))
    return m.group("par").upper() if 0<=hh<=23 and 0<=mm<=59 else None
def nat(p):
    a,b=p.split("/"); return "REAL" if a in MAJORS and b in MAJORS else "OTC"
def cls(t):
    if not t: return None
    f=t.strip().splitlines()[0]; u=f.upper()
    if "WIN" in u and "DIRECTO" in u: return "WD"
    if "WIN" in u and "GALE" in u: return "WG"
    if f.strip().startswith("❌") and ("ANALISIS" in u or "ANÁLISIS" in u or "SEGUIMOS OPERANDO" in u or u.strip()=="❌ PERSONAL."): return "L"
    return None

d=json.load(open("history_dump_full.json",encoding="utf-8")); d.sort(key=lambda m:m["id"])
res=[]; pend=None
for m in d:
    t=m.get("text") or ""; dt=datetime.fromisoformat(m["date"]).astimezone(timezone.utc)
    p=is_signal(t)
    if p: pend=(p,dt); continue
    r=cls(t)
    if r and pend: res.append((pend[0],r,nat(pend[0]),pend[1])); pend=None
res=[r for r in res if r[3].year==2026]

stat=collections.defaultdict(lambda:{"w":0,"l":0,"mk":None})
for p,r,mk,_ in res:
    s=stat[p]; s["mk"]=mk; s["l"]+= r=="L"; s["w"]+= r!="L"
rows=[(p,s["mk"],s["w"]+s["l"],100*s["l"]/(s["w"]+s["l"])) for p,s in stat.items() if s["w"]+s["l"]>=30]

fig=plt.figure(figsize=(16,11)); fig.suptitle("Canal — Distribuciones estadisticas 2026 (3087 ciclos, ene-jun)",fontsize=15,weight="bold")

# P1: outcome
ax=fig.add_subplot(2,2,1)
wd=sum(1 for r in res if r[1]=="WD"); wg=sum(1 for r in res if r[1]=="WG"); l=sum(1 for r in res if r[1]=="L")
ax.bar(["WIN\ndirecto","WIN\ngale","LOSS\ntotal"],[wd,wg,l],color=["#2e7d32","#7fd1c4","#c62828"])
for i,v in enumerate([wd,wg,l]): ax.text(i,v+10,f"{v}\n{100*v/len(res):.1f}%",ha="center",fontsize=10)
ax.set_title("Outcome de ciclo  (WIN-directo 51.9% = WR cruda real)"); ax.set_ylabel("ciclos")

# P2: loss% por par (real vs otc)
ax=fig.add_subplot(2,2,2)
rs=sorted(rows,key=lambda r:r[3])
labels=[f"{r[0]}" for r in rs]; vals=[r[3] for r in rs]
cols=["#8e24aa" if r[1]=="REAL" else "#ef6c00" for r in rs]
y=np.arange(len(labels)); ax.barh(y,vals,color=cols)
ax.axvline(9.85,color="red",ls="--",lw=1.5); ax.text(9.85,len(labels)-1,"  break-even 9.85%",color="red",fontsize=9,va="top")
ax.set_yticks(y); ax.set_yticklabels(labels,fontsize=7); ax.set_xlabel("loss %")
ax.set_title("Loss% por par (min 30 ops) — morado=REAL, naranja=OTC\nizq de la linea roja = +EV"); ax.invert_yaxis()

# P3: mensual
ax=fig.add_subplot(2,2,3)
mt=collections.Counter(); ml=collections.Counter()
for p,r,mk,dt in res:
    k=f"{dt.month:02d}"; mt[k]+=1; ml[k]+= r=="L"
ks=sorted(mt); lpct=[100*ml[k]/mt[k] for k in ks]
ax.plot(ks,lpct,marker="o",color="#c62828",lw=2)
ax.axhline(9.85,color="green",ls="--",lw=1.5); ax.text(0,9.85,"break-even",color="green",fontsize=9,va="bottom")
for k,v in zip(ks,lpct): ax.text(k,v+0.3,f"{v:.0f}%",ha="center",fontsize=9)
ax.set_title("Loss% por mes 2026 (sobre break-even casi todo el anio = -EV)"); ax.set_ylabel("loss %"); ax.set_xlabel("mes 2026"); ax.set_ylim(0,16)

# P4: real vs otc + direccion
ax=fig.add_subplot(2,2,4); ax.axis("off")
real=[r for r in res if r[2]=="REAL"]; otc=[r for r in res if r[2]=="OTC"]
rl=100*sum(1 for r in real if r[1]=="L")/len(real); ol=100*sum(1 for r in otc if r[1]=="L")/len(otc)
txt=(
 "RESUMEN 2026\n"
 "─────────────────────────\n"
 f"Ciclos emparejados : {len(res)}\n"
 f"WR reportada       : {100*(wd+wg)/len(res):.1f}%\n"
 f"WR cruda (directo) : {100*wd/len(res):.1f}%\n"
 f"Loss rate          : {100*l/len(res):.1f}%   (break-even 9.85%)\n"
 f"Veredicto          : -EV  ({((wd+wg)/len(res))*0.85-(l/len(res))*7.78:+.3f} stake/ciclo)\n"
 "─────────────────────────\n"
 f"REAL : {len(real):4d} ops  loss {rl:.1f}%\n"
 f"OTC  : {len(otc):4d} ops  loss {ol:.1f}%\n"
 "─────────────────────────\n"
 f"Direccion: PUT 100%  (0 CALL en todo 2026)\n"
 f"Racha max perdidas seguidas: 2  (0 triples)\n"
 "─────────────────────────\n"
 "REAL +EV (operables en IQ):\n"
 "  AUD/JPY 5%  AUD/CAD 6%  EUR/USD 8%\n"
 "  CAD/CHF 9%  CHF/JPY 9%\n"
 "REAL evitar (NZD crosses):\n"
 "  NZD/USD 19%  NZD/CAD 19%  NZD/JPY 17%"
)
ax.text(0.0,0.98,txt,va="top",ha="left",fontsize=11,family="monospace")

fig.tight_layout(rect=[0,0,1,0.97])
fig.savefig("dist_2026.png",dpi=110)
print("PNG_OK=dist_2026.png")
