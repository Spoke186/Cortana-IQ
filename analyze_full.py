# -*- coding: utf-8 -*-
"""analyze_full.py — analisis estadistico completo del canal (history_dump_full.json).

Empareja cada senal de entrada con su mensaje de resultado siguiente (misma metodologia que
analyze2.py) y produce distribuciones por par/mercado, outcome de ciclo, patrones de derrota,
estacionalidad (dia/hora/mes) y direccion. Segmenta por anio. Reporta rendimiento de
emparejamiento por anio para validar que el clasificador sigue siendo valido historicamente.
"""
import json, re, sys, collections, statistics

sys.stdout.reconfigure(encoding="utf-8")

IN = sys.argv[1] if len(sys.argv) > 1 else "history_dump_full.json"
YEAR_FILTER = sys.argv[2] if len(sys.argv) > 2 else None  # ej "2026" o None=todo

SIGNAL_RE = re.compile(r"(?P<par>[A-Z]{3}/[A-Z]{3})\s*;\s*(?P<hora>\d{2}:\d{2})\s*;\s*(?P<dir>(?i:PUT|CALL))")
# Recap de resultado: PAR;HH:MM;DIR->WIN/LOSS  -> NO es entrada (bug del parser real)
RECAP_RE = re.compile(r"[A-Z]{3}/[A-Z]{3}\s*;\s*\d{2}:\d{2}\s*;\s*(?i:PUT|CALL)\s*(?:-+>|—+>|→)")
MAJORS = {"USD","EUR","GBP","JPY","CHF","CAD","AUD","NZD"}

def is_signal(t):
    """Entrada real: matchea SIGNAL_RE y NO es linea de recap (sin flecha de resultado)."""
    m = SIGNAL_RE.search(t or "")
    if not m:
        return None, None
    # rechazar si el match va seguido de flecha (recap)
    tail = t[m.end():m.end()+6]
    if re.match(r"\s*(?:-+>|—+>|→)", tail):
        return None, None
    hh, mm = (int(x) for x in m.group("hora").split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None, None
    return m.group("par").upper(), m.group("dir").upper()

def nat(p):
    a, b = p.split("/")
    return "REAL" if a in MAJORS and b in MAJORS else "OTC"

def classify_result(t):
    if not t:
        return None
    first = t.strip().splitlines()[0]; up = first.upper()
    if "WIN" in up and "DIRECTO" in up: return "WD"
    if "WIN" in up and "GALE" in up: return "WG"
    if first.strip().startswith("❌") and ("ANALISIS" in up or "ANÁLISIS" in up or "SEGUIMOS OPERANDO" in up or up.strip()=="❌ PERSONAL."):
        return "L"
    return None

d = json.load(open(IN, encoding="utf-8"))
d.sort(key=lambda m: m["id"])

results = []  # (par, dir, outcome, market, year, month, weekday, hour, isofecha)
pending = None
sig_count = 0
for m in d:
    t = m.get("text") or ""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(m["date"]).astimezone(timezone.utc)
    par, direction = is_signal(t)
    if par:
        sig_count += 1
        pending = (par, direction, dt)
        continue
    r = classify_result(t)
    if r and pending is not None:
        p, dr, pdt = pending
        results.append((p, dr, r, nat(p), pdt.year, pdt.month, pdt.weekday(), pdt.hour, pdt.isoformat()))
        pending = None

if YEAR_FILTER:
    results = [r for r in results if str(r[4]) == YEAR_FILTER]

print(f"ARCHIVO: {IN}  | filtro anio: {YEAR_FILTER or 'TODO'}")
print(f"Senales de entrada detectadas: {sig_count} | ciclos emparejados (con resultado): {len(results)}")

# --- rendimiento de emparejamiento por anio (validacion) ---
print("\n--- emparejamiento por anio ---")
by_year = collections.Counter(r[4] for r in results)
for y in sorted(by_year):
    print(f"   {y}: {by_year[y]} ciclos")

if not results:
    print("\n(sin datos para este filtro)"); sys.exit()

N = len(results)
def pct(x): return f"{100*x/N:.1f}%"

# ================= OUTCOME DE CICLO =================
wd = sum(1 for r in results if r[2]=="WD")
wg = sum(1 for r in results if r[2]=="WG")
l  = sum(1 for r in results if r[2]=="L")
print("\n"+"="*64); print("DISTRIBUCION DE OUTCOME DE CICLO"); print("="*64)
print(f"  WIN directo : {wd:5d}  P={pct(wd)}   (WR cruda real ~coin-flip)")
print(f"  WIN en gale : {wg:5d}  P={pct(wg)}")
print(f"  LOSS total  : {l:5d}  P={pct(l)}")
print(f"  WR reportada (dir+gale): {100*(wd+wg)/N:.1f}%")
PAYOUT=0.85; FULL=7.78
be = PAYOUT/(PAYOUT+FULL)
ev = ((wd+wg)/N)*PAYOUT - (l/N)*FULL
print(f"  Break-even loss rate = {100*be:.2f}%  | loss real = {pct(l)}  -> {'+EV' if l/N<be else '-EV'}")
print(f"  EV aprox = {ev:+.3f} stake/ciclo")

# ================= POR PAR =================
stat = collections.defaultdict(lambda: {"wd":0,"wg":0,"l":0,"mk":None})
for p,dr,r,mk,*_ in results:
    s=stat[p]; s["mk"]=mk
    s["wd"]+= r=="WD"; s["wg"]+= r=="WG"; s["l"]+= r=="L"
rows=[]
for p,s in stat.items():
    w=s["wd"]+s["wg"]; tot=w+s["l"]
    rows.append((p,s["mk"],tot,w,s["wd"],s["wg"],s["l"],100*w/tot,100*s["l"]/tot))

def show(title, rs, n=15):
    print(f"\n--- {title} ---")
    print(f"   {'PAR':9s}{'MKT':5s}{'OPS':>5s}{'WIN':>5s}{'DIR':>5s}{'GAL':>5s}{'LOS':>5s}{'WR':>6s}{'LOSS%':>7s}")
    for p,mk,tot,w,a,b,c,wr,lr in rs[:n]:
        print(f"   {p:9s}{mk:5s}{tot:5d}{w:5d}{a:5d}{b:5d}{c:5d}{wr:5.0f}%{lr:6.0f}%")

print("\n"+"="*64); print("DISTRIBUCION POR MERCADO"); print("="*64)
show("MAS VOLUMEN (ops)", sorted(rows,key=lambda r:-r[2]))
show("MEJOR WR (min 30 ops)", sorted([r for r in rows if r[2]>=30],key=lambda r:-r[7]))
show("PEOR WR (min 30 ops)", sorted([r for r in rows if r[2]>=30],key=lambda r:r[7]))

# ================= REAL vs OTC =================
print("\n"+"="*64); print("REAL vs OTC"); print("="*64)
for mk in ("REAL","OTC"):
    sub=[r for r in results if r[3]==mk]; n=len(sub)
    if not n: continue
    sl=sum(1 for r in sub if r[2]=="L")
    sd=sum(1 for r in sub if r[2]=="WD")
    print(f"  {mk}: {n} ops ({100*n/N:.0f}%) | WR {100*(n-sl)/n:.1f}% | loss {100*sl/n:.1f}% | WIN-dir {100*sd/n:.1f}% | falla 1/{n/sl:.1f}")

# ================= DIRECCION =================
print("\n"+"="*64); print("DIRECCION (sesgo del senalero)"); print("="*64)
dc=collections.Counter(r[1] for r in results)
for k in ("PUT","CALL"):
    print(f"  {k}: {dc[k]} ({100*dc[k]/N:.1f}%)")

# ================= PATRON DE DERROTAS =================
seq=["L" if r[2]=="L" else "W" for r in results]
loss_runs=[]; run=0
for o in seq:
    if o=="L": run+=1
    elif run: loss_runs.append(run); run=0
if run: loss_runs.append(run)
runc=collections.Counter(loss_runs)
prevL=sum(1 for i in range(1,N) if seq[i-1]=="L")
prevLL=sum(1 for i in range(1,N) if seq[i-1]=="L" and seq[i]=="L")
print("\n"+"="*64); print("PATRON DE DERROTAS"); print("="*64)
print(f"  Falla 1 cada {N/l:.1f} ops | tasa base {pct(l)}")
print(f"  Prob perder normal {pct(l)} vs tras perder {100*prevLL/prevL:.1f}%  (clustering={'SI' if prevLL/prevL>l/N else 'no'})")
print("  Rachas de perdida seguidas:")
for k in sorted(runc):
    print(f"     {k} seguida(s): {runc[k]} veces")
maxrun=max(loss_runs) if loss_runs else 0
print(f"  Racha MAX de perdidas seguidas: {maxrun}  (costo ~ -{sum([1,2.15,4.63,9.97,21.4][:maxrun]):.1f} stake si pasara en 1 ciclo encadenado)")

# ================= ESTACIONALIDAD =================
dias=["Lun","Mar","Mie","Jue","Vie","Sab","Dom"]
print("\n"+"="*64); print("ESTACIONALIDAD"); print("="*64)
wdl=collections.Counter(); wdt=collections.Counter()
for r in results:
    wdt[r[6]]+=1; wdl[r[6]]+= r[2]=="L"
print("  Por dia de semana:")
for w in range(7):
    if wdt[w]: print(f"     {dias[w]}: {wdl[w]}/{wdt[w]} ({100*wdl[w]/wdt[w]:.0f}% loss)")
hl=collections.Counter(); ht=collections.Counter()
for r in results:
    ht[r[7]]+=1; hl[r[7]]+= r[2]=="L"
print("  Por hora UTC (>=30 ops):")
for h in range(24):
    if ht[h]>=30: print(f"     {h:02d}:00 {hl[h]:3d}/{ht[h]:3d} ({100*hl[h]/ht[h]:.0f}% loss)")
ml=collections.Counter(); mt=collections.Counter()
for r in results:
    key=f"{r[4]}-{r[5]:02d}"; mt[key]+=1; ml[key]+= r[2]=="L"
print("  Por mes (loss% y volumen):")
for k in sorted(mt):
    print(f"     {k}: {mt[k]:4d} ops, {100*ml[k]/mt[k]:4.0f}% loss")
