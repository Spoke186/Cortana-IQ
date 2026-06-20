# Telegram → Deriv — Bot de Copy Trading (handoff para Claude Code)

> Documento de instrucciones. Autor del resumen: Claude (sesión con Esteban).
> Propósito: que Claude Code construya, desde cero, un bot que lee señales de un canal de
> Telegram y las replica como contratos Rise/Fall en Deriv, con Gale automático.
> Esto NO es BMO. Es un proyecto nuevo, separado. No tiene estrategia propia: es **copy trade puro**.

---

## 0. Qué es y qué NO es

**Es:** un bot que (1) escucha un canal de Telegram, (2) parsea señales de opciones binarias
estilo `PAR/PAR;HH:MM;PUT|CALL`, (3) ejecuta el contrato equivalente Rise/Fall en Deriv vía API
a la hora exacta indicada, (4) aplica Gale automático si pierde, (5) avisa el resultado por un
bot propio de Telegram.

**NO es:** un sistema con estrategia, señales propias, ni optimización. El bot no decide nada de
trading. Solo obedece lo que llega del canal. Cero lógica de mercado propia.

**Dinero real desde el arranque.** Esteban lo prueba con cuenta real y stake mínimo ($1). No hay
modo demo obligatorio; el código opera en vivo. La seguridad viene del stake bajo, no de un sandbox.

---

## 1. La señal (formato canónico a parsear)

El canal envía DOS tipos de mensaje. El bot SOLO acciona el primero; ignora el segundo.

### 1.1 Señal de entrada (ACCIONAR)
Formato literal del bloque relevante dentro del mensaje:
```
USD/TRY;00:45;PUT 🟥
🕐 TIEMPO HASTA 00:50
1er GALE —> TIEMPO HASTA 00:55
2º GALE —> TIEMPO HASTA 01:00
```
- Línea clave a parsear con regex: `(?P<par>[A-Z]{3}/[A-Z]{3});(?P<hora>\d{2}:\d{2});(?P<dir>PUT|CALL)`
- `par`: dos códigos ISO de 3 letras separados por `/` (ej. USD/TRY, EUR/JPY, NZD/USD).
- `hora`: hora de ENTRADA en formato HH:MM. **Está en zona horaria UTC-3** (ver §2).
- `dir`: `PUT` (= Fall/Bajar) o `CALL` (= Rise/Subir).
- Las líneas de GALE dan las horas de los reintentos: entrada + 5 min = Gale 1, +10 min = Gale 2.
  El bot puede DERIVAR estas horas (hora_entrada + 5 y +10 min) en vez de parsearlas; deben coincidir.
  Si no coinciden con lo parseado, loguear warning y usar las horas derivadas (entrada+5, +10).

### 1.2 Reporte diario / resumen (IGNORAR)
Mensajes con `->WIN`, `->LOSS`, listas de resultados, conteos "8 WINS / 0 LOSS", mensajes
motivacionales, anuncios, "Pinned Message", etc. El bot NO debe accionar nada de esto.
Heurística: si la línea no matchea el regex de §1.1 exactamente, ignorar el mensaje.

---

## 2. Zona horaria (CRÍTICO — un error aquí vacía la cuenta)

- La hora de la señal (`00:45`) está en **UTC-3** (el canal lo declara: "Zona horaria: UTC-3").
- Esteban está en Colombia (**UTC-5**). El bot puede correr en cualquier máquina/zona.
- **Regla de implementación:** interpretar la hora de la señal como hora local de la TZ configurada
  en `.env` (`SIGNAL_TIMEZONE=America/Sao_Paulo`, que es UTC-3 sin DST relevante para este uso),
  convertir a UTC, y programar la ejecución contra UTC. NUNCA usar la hora local de la máquina.
- Si la hora de entrada convertida a UTC ya pasó en el momento en que llega el mensaje →
  **NO operar**, loguear "señal vencida, saltada" y avisar por Telegram.
- Manejar el cruce de medianoche: si la hora de la señal es 23:58 y los Gale caen en 00:03, 00:08
  del día siguiente, calcular bien las fechas (usar datetime con TZ, no aritmética de strings).

---

## 3. Timing de ejecución

- El bot ejecuta a la **hora exacta de la señal**, no cuando llega el mensaje.
  - Mensaje llega antes de la hora → esperar (scheduler) hasta la hora exacta, luego ejecutar.
  - Mensaje llega después de la hora → saltar (§2).
- Cada contrato es **Rise/Fall de 5 minutos exactos** desde la hora de entrada. Fijo. Siempre 5 min.
- Definición de resultado (la nativa de Deriv Rise/Fall):
  - `PUT`/Fall gana si el precio al cierre de los 5 min < precio de entrada.
  - `CALL`/Rise gana si el precio al cierre de los 5 min > precio de entrada.
  - El API de Deriv reporta el resultado del contrato; el bot lo lee, no lo calcula a mano.

---

## 4. Lógica de Gale (martingala — VERSIÓN META-CONSTANTE de Esteban)

**NO usar el Gale del canal (doblar ×2).** Usar la fórmula de meta constante, que mantiene la
misma ganancia objetivo del ciclo sin importar en qué nivel se gane.

### 4.1 Fórmula
Para cada nivel n, la apuesta cubre todo lo perdido en niveles anteriores + la meta:
```
meta = INITIAL_STAKE * payout            # payout leído en vivo de Deriv (fracción, ej. 0.90)
apuesta_n = (perdido_acumulado_antes + meta) / payout
apuesta_n = redondear_hacia_arriba_al_centavo(apuesta_n)   # nunca quedar corto
```

### 4.2 Ejemplo con INITIAL_STAKE=$1 y payout=0.90 (referencia; el bot usa el payout REAL de cada contrato)
| Nivel   | Apuesta | Perdido antes | Neto del ciclo si gana aquí |
|---------|---------|---------------|------------------------------|
| Entrada | $1.00   | $0.00         | +$0.90                       |
| Gale 1  | $2.11   | $1.00         | +$0.90                       |
| Gale 2  | $4.46   | $3.11         | +$0.90                       |
| Pierde 3| —       | —             | −$7.57                       |

### 4.3 Reglas de Gale
- Máximo **2 niveles de Gale** (entrada + Gale 1 + Gale 2). NO hay 4ª entrada. Si Gale 2 pierde,
  el ciclo termina en pérdida; loguear y avisar.
- Los Gale son **automáticos**: si un nivel pierde, el bot dispara el siguiente a su hora
  (entrada+5, entrada+10), SIN esperar nuevo mensaje del canal.
- **Misma dirección** que la entrada original en todos los Gale (el canal lo exige; el bot lo respeta).
- **Payout real:** el bot lee el payout de cada `proposal` de Deriv antes de comprar y recalcula la
  apuesta del Gale con ese número. No asumir 90% fijo. Si el payout varía entre niveles, recalcular.
- Si el par no existe en Deriv (§6), no se entra a ningún nivel del ciclo.

---

## 5. Stake y cuenta

- `INITIAL_STAKE = 1.00` USD (configurable en `.env`). Esteban lo sube manualmente si valida el WR.
- Deriv acepta stakes decimales; mínimo ~$0.35. Las apuestas de Gale ($2.11, $4.46) son válidas.
- **Circuit breaker: preparado pero DESACTIVADO.** Incluir parámetro `STOP_LOSS_BALANCE=None` en
  config. Si está en None, no hace nada. Si se le pone un número (ej. 50), el bot deja de operar
  cuando el balance cae por debajo. Implementarlo apagado por defecto; cero comportamiento ahora.
  (Misma disciplina que BMO: parámetros default-off, listos para activar sin reescribir.)

---

## 6. Mapeo de símbolos Deriv

- Los pares del canal (`EUR/JPY`) se mapean al símbolo interno de Deriv (`frxEURJPY`).
- Construir el símbolo: `"frx" + par.replace("/", "")`. Validar contra la lista real de activos
  que devuelve Deriv (`active_symbols` API) antes de operar.
- **Si el par NO está disponible en Deriv** (probable para exóticos como USD/TRY, USD/IDR):
  NO operar, loguear "mercado no encontrado: {par}", avisar por Telegram. No intentar fallback.
- Validar también que el mercado esté **abierto** a la hora de la señal (`active_symbols` indica
  `exchange_is_open`). Si está cerrado, no operar y avisar.

---

## 7. Conexión Deriv (API)

- WebSocket: `wss://ws.derivws.com/websockets/v3?app_id={APP_ID}`
- Librería: `python-deriv-api` (oficial, `deriv-com/python-deriv-api`). Maneja ws + reconexión.
- Auth: token de API generado en app.deriv.com → Settings → API Token, con permisos
  **Read + Trade + Payments**. Va en `.env` como `DERIV_API_TOKEN`. App_id se registra en
  api.deriv.com (gratis) → `.env` como `DERIV_APP_ID`.
- Flujo de una operación:
  1. `active_symbols` → validar par disponible + abierto (§6).
  2. `proposal` con `contract_type=PUT|CALL`, `symbol`, `duration=5`, `duration_unit=m`,
     `amount=<apuesta>`, `basis=stake`, `currency=USD`. Devuelve `ask_price` y `payout`.
  3. Leer `payout` real para el cálculo de Gale (§4).
  4. `buy` con el `proposal.id` y `price`.
  5. Suscribirse a `proposal_open_contract` para esperar el settlement (is_sold / status).
  6. Leer resultado (`status` = won/lost), registrar, decidir Gale.
- **Reconexión:** si el ws cae, reconectar y reautenticar. No perder el rastro de un ciclo en curso.
- **Seguridad:** nunca colocar más de lo que la fórmula dicta. Nunca operar fuera de una señal.

---

## 8. Avisos por Telegram (bot propio — NO el canal del señalero)

- Bot propio creado con BotFather. `.env`: `NOTIFY_BOT_TOKEN`, `NOTIFY_CHAT_ID` (chat de Esteban).
- **Codificación UTF-8 explícita** en los envíos (aprendizaje de BMO: WebClient/requests deben
  forzar UTF-8 o los acentos rompen el envío; con `requests` y `python-telegram-bot` esto ya es
  UTF-8 por defecto, pero verificar). Mensajes con acentos: Dirección, Operación, Sesión.
- **Nunca** un `catch {}` vacío que oculte errores de envío. Loguear todo fallo de Telegram a archivo.
- Eventos a notificar:
  - Señal recibida y programada: par, dirección, hora de entrada (en hora Colombia y UTC-3), stake.
  - Señal saltada: par no encontrado / mercado cerrado / señal vencida (con motivo).
  - Apertura de cada nivel (entrada, Gale 1, Gale 2): par, dirección, apuesta, payout real.
  - Resultado de cada nivel: ganó/perdió, monto.
  - Cierre de ciclo: resultado neto (+$0.90 o −$7.57 según corresponda), balance actualizado.

---

## 9. Logging (para medir el WR REAL crudo)

El propósito central de la primera fase: **medir el win rate CRUDO por entrada** (no el inflado
por Gale que muestra el canal). Esto decide si el sistema es EV-positivo.

- CSV append por cada NIVEL ejecutado: timestamp, par, símbolo Deriv, dirección, nivel
  (entrada/gale1/gale2), apuesta, payout real, precio entrada, precio cierre, resultado
  (won/lost), contract_id, balance después.
- CSV append por cada CICLO: timestamp, par, dirección, nivel donde se resolvió, resultado del
  ciclo (win/loss), neto del ciclo, balance.
- Métrica derivada a reportar (script aparte o resumen diario por Telegram):
  - **WR crudo por entrada** = (entradas directas ganadas) / (total entradas). ESTE es el número
    que importa, no el del canal.
  - WR por ciclo (cuántos ciclos terminan en win contando Gale).
  - Distribución: % resuelto en entrada / Gale 1 / Gale 2 / perdido.
  - Neto acumulado, drawdown.
- Log de errores aparte (`errors.log`): fallos de API, Telegram, parsing, timing.

---

## 10. Estructura de archivos propuesta

```
telegram-deriv-bot/
  .env                  # credenciales y parámetros (NUNCA al repo; .gitignore)
  .env.example          # plantilla sin secretos
  config.py             # carga .env, constantes (stake, niveles Gale, TZ, circuit breaker)
  listener.py           # telethon: escucha el canal, pasa mensajes crudos al parser
  parser.py             # regex §1, distingue señal vs resumen, extrae par/hora/dir
  scheduler.py          # convierte hora UTC-3 → UTC, programa ejecución a la hora exacta
  deriv_client.py       # ws Deriv: active_symbols, proposal, buy, espera settlement
  gale.py               # fórmula meta-constante §4, decide niveles, calcula apuestas
  notifier.py           # bot propio Telegram, envíos UTF-8, sin catch vacío
  logger.py             # CSV niveles + ciclos + errores
  main.py               # orquesta: listener → parser → scheduler → deriv → gale → notifier → logger
  requirements.txt      # telethon, python-deriv-api, python-telegram-bot (o requests), python-dotenv, pytz
  README.md             # setup en Windows, cómo sacar credenciales, cómo correr
```

---

## 11. Credenciales necesarias (Esteban las consigue durante el setup)

- **Telethon (leer canal):** `TG_API_ID` + `TG_API_HASH` de https://my.telegram.org (cuenta de usuario).
- **Canal a escuchar:** `TG_CHANNEL` (username o id del canal del señalero).
- **Deriv:** `DERIV_API_TOKEN` (app.deriv.com, permisos Read+Trade+Payments) + `DERIV_APP_ID`
  (registrar app en api.deriv.com).
- **Bot de avisos:** `NOTIFY_BOT_TOKEN` (BotFather) + `NOTIFY_CHAT_ID`.
- Todo en `.env`. `.env` en `.gitignore`. Nunca secretos en código.

---

## 12. Parámetros fijos (resumen para que no haya ambigüedad)

| Parámetro            | Valor                         |
|----------------------|-------------------------------|
| Stake inicial        | $1.00 USD                     |
| Niveles de Gale      | 2 (entrada + Gale 1 + Gale 2) |
| Gale                 | meta-constante (§4), NO ×2    |
| Duración contrato    | 5 minutos exactos             |
| TZ de la señal       | UTC-3 (America/Sao_Paulo)     |
| Producto Deriv       | Rise/Fall (CALL/PUT)          |
| Modo                 | real (live), copy trade puro  |
| Circuit breaker      | preparado, DESACTIVADO (None) |
| Par no disponible    | no operar + avisar            |
| Mercado cerrado      | no operar + avisar            |
| Señal vencida        | no operar + avisar            |

---

## 13. Orden de construcción sugerido (para Claude Code)

1. `config.py` + `.env.example` + `requirements.txt` + esqueleto de carpetas.
2. `parser.py` con tests unitarios sobre el formato §1 (señal válida, resumen a ignorar, edge cases).
3. `scheduler.py` con tests de conversión TZ (UTC-3 → UTC) incluyendo cruce de medianoche.
4. `gale.py` con tests de la fórmula §4 (valores esperados: $1.00 / $2.11 / $4.46; neto +$0.90 / −$7.57).
5. `deriv_client.py` (probar primero con `active_symbols` y `proposal` SIN comprar, para ver payouts reales).
6. `notifier.py` + `logger.py`.
7. `listener.py` + `main.py` (integración).
8. Prueba end-to-end con stake $1 real en una sesión observada por Esteban.

---

## 14. Advertencias que Claude Code debe respetar

- **El WR del canal (16/0, etc.) NO es el WR crudo.** Cuenta los Gale como wins. El objetivo del
  logging (§9) es medir el WR crudo real por entrada. No confiar en los números del canal.
- La rentabilidad del sistema depende enteramente del WR crudo. Con payout 90%, el break-even
  está ~53% de WR crudo por entrada. Por debajo, el sistema es EV-negativo y quiebra la cuenta
  con certeza estadística (un ciclo completo perdido cuesta 7.57× el stake). El bot solo ejecuta;
  la decisión de seguir/parar es de Esteban con base en el WR medido.
- Esteban es ingeniero físico: el código y los reportes deben ser precisos y verificables.
  Logs claros, números auditables, sin narrativa de "vas ganando".
- Nunca secretos en código. Nunca operar fuera de una señal válida. Nunca exceder la apuesta
  que dicta la fórmula. Nunca ocultar errores con catch vacío.