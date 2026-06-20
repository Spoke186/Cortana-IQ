# telegram-iq-bot

Copy trading **puro**: lee senales de un canal de Telegram y las replica como **turbo options
de 5 min** en IQ Option (CALL/PUT), con Gale automatico (martingala de meta constante).
**Sin estrategia propia.** El bot solo obedece la senal del canal.

> ⚠️ **Dinero real desde el arranque** (si `IQ_ACCOUNT_TYPE=real`). Opera en vivo con stake
> minimo ($1). La seguridad viene del stake bajo, no de un sandbox. Valida primero en
> `practice` (demo). Lee §14 del documento de instrucciones antes de subir el stake.

> ⚠️ **API no oficial.** `iqoptionapi` es una libreria de comunidad (ingenieria inversa), no
> oficial. Va contra los ToS de IQ Option (riesgo de baneo) y puede romperse cuando IQ cambia
> su backend. Las **digital options** de la lib estan rotas hoy ("GetUnderlyingList V2 is not
> supported"); por eso el bot usa **turbo** (1-5 min), que si funciona.

---

## Que hace

1. Escucha un canal de Telegram (`listener.py`, telethon, cuenta de usuario).
2. Parsea senales `PAR/PAR;HH:MM;PUT|CALL` e ignora todo lo demas (`parser.py`).
3. Convierte la hora (UTC-3) a UTC y programa la ejecucion a la hora exacta (`scheduler.py`).
4. Ejecuta una **turbo option de 5 min** en IQ Option (`iqoption_client.py`).
5. Si pierde, dispara Gale 1 (+5 min) y Gale 2 (+10 min) automaticos, misma direccion (`gale.py`).
6. Avisa cada evento por un bot PROPIO de Telegram (`notifier.py`).
7. Loguea cada nivel y ciclo a CSV auditable (`logger.py`) para medir el **WR crudo** (`metrics.py`).

### Pares y OTC (importante)

El par de la senal (`USD/TRY`) se mapea a `USDTRY`. Si ese mercado esta cerrado (fin de
semana), IQ solo abre la variante **`USDTRY-OTC`**, con **precio sintetico propio de IQ**, no
el mercado real en que se basa la senal. El bot opera lo que este abierto (prefiere el par
real; cae a `-OTC`) y lo deja registrado. Operar `-OTC` no rastrea el subyacente del canal:
decision de Esteban. Si el par no existe en IQ (ni real ni `-OTC`), no opera y avisa.

## Modelo de Gale (meta constante, §4)

Para cada nivel la apuesta cubre lo perdido antes + la meta del ciclo:

    meta      = INITIAL_STAKE * payout_real
    apuesta_n = (perdido_acumulado + meta) / payout_real   (redondeada al centavo)

Maximo 2 niveles de Gale (entrada + Gale 1 + Gale 2). Si Gale 2 pierde, el ciclo cierra en perdida.

**Redondeo (`GALE_ROUNDING` en `.env`):** `ceil` (default, "nunca quedar corto", §4.1) o
`nearest` (tabla §4.2). El payout es el **real** de cada turbo de IQ (`get_all_profit`, ej.
0.87 = +87%), no un valor fijo. El break-even sube cuando el payout baja: con 87% el WR crudo
de break-even es ~53.5%; por debajo el sistema es EV-negativo.

---

## Setup en Windows

### 1. Python y dependencias

```powershell
cd telegram-deriv-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`iqoptionapi` se instala **desde GitHub** (la version de PyPI es un stub viejo sin
`stable_api`). `requirements.txt` ya apunta al repo. `tzdata` es obligatorio en Windows.

### 2. Credenciales (todas van en `.env`)

```powershell
copy .env.example .env
notepad .env
```

- **Telethon** (leer el canal): `TG_API_ID` + `TG_API_HASH` de https://my.telegram.org
  (API development tools). `TG_CHANNEL` = @usuario o id del canal (privado: `-100XXXXXXXXXX`).
- **IQ Option**: `IQ_EMAIL` + `IQ_PASSWORD` (tu login de IQ — la lib no usa token acotado,
  usa la cuenta completa). `IQ_ACCOUNT_TYPE` = `practice` (demo) o `real`.
- **Bot de avisos**: crea un bot con @BotFather → `NOTIFY_BOT_TOKEN`. `NOTIFY_CHAT_ID` = tu chat
  id (sacalo con @userinfobot). Mandale `/start` a tu bot o no podra escribirte.

### 3. Primer login de Telethon

El primer arranque pide tu telefono + el codigo que Telegram te manda (se guarda en
`*.session`). Usa la cuenta que ESTA suscrita al canal.

### 4. Correr

```powershell
python main.py
```

Verifica que llega el aviso "🟢 Bot iniciado" a tu Telegram con el balance.

### 5. Validacion previa (antes de arriesgar dinero)

Con `IQ_ACCOUNT_TYPE=practice`, prueba login + listado de assets abiertos + payout turbo
sin esperar senales. Script minimo:

```powershell
python -c "import os; from dotenv import load_dotenv; load_dotenv(); \
from iqoptionapi.stable_api import IQ_Option; \
iq=IQ_Option(os.getenv('IQ_EMAIL'),os.getenv('IQ_PASSWORD')); print(iq.connect()); \
iq.change_balance('PRACTICE'); print('balance',iq.get_balance()); \
print('payout EURUSD-OTC', iq.get_all_profit().get('EURUSD-OTC',{}).get('turbo'))"
```

Si el login lo frena un captcha/2FA, es el riesgo conocido de la lib (ver advertencia arriba).
El flujo de compra solo se dispara con una senal real del canal.

---

## Prueba OFFLINE (sin red, sin dinero, sin credenciales)

Confirma que el bot SABE cual mensaje es la senal y que horas/apuestas planearia:

```powershell
python dryrun.py "USD/TRY;00:45;PUT 🟥"      # senal -> par, horas (Col/UTC-3/UTC), apuestas
python dryrun.py "8 WINS / 0 LOSS HOY"        # ruido -> "NO es senal. La IGNORA"
python dryrun.py                              # pega el texto y Ctrl+Z + Enter
```

`dryrun.py`, `metrics.py` y los tests corren SIN `.env`: las credenciales solo se exigen al
arrancar `main.py` (en `config.validate()`), no al importar.

## Reporte de WR crudo (el numero que importa, §9/§14)

```powershell
python metrics.py
```

Muestra el **WR crudo por entrada** (no el inflado por Gale del canal), la distribucion de
resolucion (entrada/Gale 1/Gale 2/perdido), neto acumulado y drawdown.

---

## Tests

```powershell
python -m pytest tests/ -q
```

Cubren parser (§1), scheduler (TZ + cruce de medianoche, §2/§3), gale (formula, ambos
redondeos, §4) e integracion con un broker FALSO (sin tocar IQ ni dinero).

---

## Archivos

| archivo               | rol |
|-----------------------|-----|
| `config.py`           | carga `.env`, constantes, validacion |
| `parser.py`           | regex §1, senal vs resumen |
| `scheduler.py`        | UTC-3 → UTC, horas de entrada/Gale, vencida/medianoche |
| `gale.py`             | formula meta-constante §4 |
| `iqoption_client.py`  | IQ Option (turbo): login, check_symbol, payout, buy + settlement |
| `notifier.py`         | bot propio de avisos (UTF-8, sin catch vacio) |
| `logger.py`           | CSV niveles + ciclos + `errors.log` |
| `metrics.py`          | reporte WR crudo |
| `listener.py`         | telethon: escucha el canal |
| `main.py`             | orquesta todo |
| `dryrun.py`           | prueba offline: que haria el bot con un mensaje |

---

## Reglas que el bot respeta (§14)

- Nunca opera fuera de una senal valida. Nunca excede la apuesta que dicta la formula.
- Par no disponible / mercado cerrado / senal vencida → no opera + avisa.
- Circuit breaker preparado pero DESACTIVADO por defecto (`STOP_LOSS_BALANCE=None`).
- Nunca secretos en codigo (`.env` en `.gitignore`). Nunca un catch vacio que oculte errores.
- El WR del canal NO es el WR crudo. La decision de seguir/parar es de Esteban con el WR medido.
