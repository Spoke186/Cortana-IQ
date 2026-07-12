# Análisis estadístico y racional de stakes — Cortana-IQ

**Fecha del análisis:** 2026-07-11 · **Bankroll de referencia:** $850 · **Broker:** IQ Option (turbo 5 min, payout ~87%)

Este documento consolida el análisis estadístico de los tres proveedores de señales y explica
por qué la tabla de stakes (`STAKE_TABLE` en `config.py`) está como está.

---

## 1. Metodología

### 1.1 Construcción del dataset (`analyze_full.py`)

- Se exporta el historial completo de cada canal de Telegram (`export_history.py` → `history_dump_full.json`).
- Cada **señal de entrada** (`PAR;HH:MM;PUT/CALL`) se empareja con el **mensaje de resultado**
  inmediatamente posterior. Las líneas de recap (`PAR;HH:MM;DIR -> WIN`) se descartan para no
  duplicar entradas.
- Cada ciclo se clasifica en tres outcomes: **WD** (win directo), **WG** (win en gale), **L** (loss total).
- Ventana de datos: desde **feb-2025**. Se segmenta por año para validación IS/OOS (ver §1.2).
- El script reporta además: WR por par, REAL vs OTC, sesgo de dirección, clustering de derrotas
  (¿pierde más después de perder?), rachas máximas de pérdida y estacionalidad (día/hora/mes).

### 1.2 Selección de stakes por Monte Carlo (`mc_stake.py`)

No elegimos stakes "a ojo": se barrió un grid de combinaciones con **bootstrap Monte Carlo**:

- **Grid:** stake_alto ∈ {5, 8, 12} × stake_estándar ∈ {1, 2, 3} × gale_max ∈ {0, 1},
  en 2 escenarios (A = todos los pares, B = solo subset EV+).
- **Validación:** IS = ciclos de 2025 (in-sample), OOS = ciclos de 2026 (out-of-sample, mismos
  parámetros sin re-optimizar).
- **Simulación:** 10,000 paths por combinación, resampleando con reemplazo la secuencia real de
  ciclos. Payout fijo 0.87, redondeo de gale `ceil` (igual que producción).
- **Métricas por combinación:** distribución del capital final (p5/p50/p95), **probabilidad de
  ruina** (capital no alcanza para la siguiente entrada), max drawdown (p50/p95) y EV analítico
  por ciclo.
- Detalle de modelado: los mensajes "WIN en gale" no dicen en qué nivel ganó, así que el nivel se
  sortea con P(gale1 | WG) = 1/(2−p), donde p = 1 − ∛(lossP) es la probabilidad de acierto por
  período implícita en la tasa de loss de ciclo.

**Hallazgo clave del MC:** gale 0 colapsa en OOS (demasiada varianza por ciclo perdido barato pero
frecuente), y stakes altos con 2 gale disparan la probabilidad de ruina. De ahí la regla de sizing
de §3.

---

## 2. Resultados por proveedor y decisión

### 2.1 Canal principal ("main") — EV negativo crudo → cirugía de pares

El canal completo es perdedor. Break-even con 2 gale: loss rate máximo ≈ payout/(payout+costo
ciclo completo) ≈ **9.9%**; el canal está por encima. Decisión: **cortar perdedores, subir ganadores**.

| Par | WR histórica | Decisión | Stake |
|---|---|---|---|
| USD/CHF, CAD/JPY, USD/PHP, USD/COP, USD/BRL | < 45% | **NO operar** | $0 |
| USD/BDT, USD/INR, CAD/CHF | > 65% | Subir | $7 (peor ciclo ~$54) |
| AUD/JPY, AUD/CAD | mejores EV del canal | Stake alto | $8 (peor ciclo ~$62) |
| Resto majors (bucket REAL) | — | Stake base | $5 (peor ciclo ~$39) |
| Resto exóticos (bucket OTC) | — | Stake mínimo | $3 (peor ciclo ~$23) |

Gale: **2 niveles** (entrada + G1 + G2, separados 5 min).

### 2.2 GOLD TRADER — WR ~70% en majors → stakes grandes SIN gale

- WR ~70% concentrada en 3 majors. Se opera **sin martingala**: el riesgo por trade = stake
  (no se multiplica ~8x como con 2 gale). Eso permite stakes grandes con menos riesgo de cola.

| Par | WR | Stake |
|---|---|---|
| EUR/JPY | 73% | $25 |
| EUR/USD | 69% | $18 |
| GBP/USD | 68% | $18 |

Pares fuera de la tabla: stake plano $10. TZ del canal: UTC-3.

### 2.3 SEÑALES CONSISTENTES VIP — crudo perdedor (48.7% WR) → whitelist + filtro de tendencia

- El canal crudo pierde. Pero un subconjunto de pares es EV+ **cuando la señal va a favor de la
  tendencia** medida a la hora de entrada. Decisión: **whitelist-only** (todo par fuera de la
  lista NO se opera) + filtro de tendencia obligatorio.

| Par | WR a-favor de tendencia | n (muestra) | Stake |
|---|---|---|---|
| EUR/GBP | 64.7% | 85 | $8 |
| GBP/AUD | 64.1% | 39 (chica) | $6 |
| EUR/USD | 59.6% | 57 | $6 |
| EUR/NZD | 57.1% | 28 (chica) | $6 |

Gale: **2 niveles** → peor ciclo ≈ 8× base. Con base $8 el peor ciclo es ~$62 ≈ 7% del bankroll.
TZ del canal: UTC-5.

### 2.4 Filtro de tendencia

- EMA **9 vs 21** en la timeframe de la señal (M1 → velas 60s, M5 → velas 300s).
- Si la señal va **contra** la tendencia medida al momento de entrada → **no se opera**.
- Activo en CONSISTENTES (es lo que vuelve EV+ su whitelist); apagado en GOLD (su WR ya es alta
  sin filtro).

---

## 3. Regla de sizing (la fórmula detrás de todos los números)

1. **Costo del peor ciclo con 2 gale ≈ 7.8–8× el stake base** (entrada + gale1 + gale2 con
   redondeo ceil al centavo, payout 0.87: 1 + 2.15 + 4.63 ≈ 7.78×).
2. **Restricción:** el peor ciclo de cualquier par ≤ **~7% del bankroll** ($850 → ~$62).
   Por eso el stake máximo con 2 gale es $8.
3. **Sin gale, riesgo = stake**, así que GOLD puede llevar $18–25 con exposición por trade
   comparable o menor a la de un ciclo de 2 gale con base $3–8.
4. Par con WR < break-even o sin muestra suficiente → $0 (no operar) o bucket mínimo.

---

## 4. Reproducir el análisis

```bash
# 1. exportar historial del canal
python export_history.py            # -> history_dump_full.json

# 2. estadística descriptiva completa (por par, mercado, estacionalidad, rachas)
python analyze_full.py history_dump_full.json        # todo
python analyze_full.py history_dump_full.json 2026   # solo 2026

# 3. Monte Carlo de combinaciones de stake (grid completo IS/OOS)
python mc_stake.py                  # -> mc_results.csv, mc_finals.pkl
python report_mc.py                 # reporte legible del CSV
```

Los dumps de historial y CSVs de resultados no están versionados (datos crudos, pesados); los
scripts sí, y regeneran todo desde el canal.

---

## 5. Configuración vigente

La tabla operativa vive en `config.py` (`STAKE_TABLE`, `STAKE_ALTO/REAL/OTC`, `GALE_*`,
`TREND_EMA_*`). Ese archivo es la fuente de verdad; este documento explica el porqué.
