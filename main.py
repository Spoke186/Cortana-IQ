"""
main.py — orquesta: listener -> parser -> scheduler -> broker(IQ) -> gale -> notifier -> logger. (§10, §13.7)

Modo: copy trade puro sobre IQ Option (turbo 5min). El bot NO decide nada de trading;
obedece la senal (§0).
"""
from __future__ import annotations

import asyncio
import html
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Consola Windows = cp1252; los prints con emoji reventarian. Forzar UTF-8 en stdout.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import config
import iqoption_client as broker_mod
import gale
import logger
import notifier
import providers
import scheduler
from listener import build_client
from parser import Signal
from providers import Provider

_TWO = Decimal("0.01")


# ----------------------------------------------------------------------
#  Helpers
# ----------------------------------------------------------------------
def _money(x: Decimal | None) -> str:
    if x is None:
        return "?"
    return f"${x.quantize(_TWO)}"


def _level_name(level: int) -> str:
    return {0: "Entrada", 1: "Gale 1", 2: "Gale 2"}.get(level, f"Nivel {level}")


# Badge visual por proveedor: emoji + nombre corto en mayusculas.
_PROV_BADGE = {
    "main": "🟣 MAIN",
    "consistentes": "🔵 CONSISTENTES",
    "gold": "🟡 GOLD",
}


def _tag(source: str) -> str:
    return _PROV_BADGE.get(source, f"⚪ {source.upper()}")


def _esc(s) -> str:
    """Escapa texto dinamico para HTML de Telegram (errores pueden traer < > &)."""
    return html.escape(str(s), quote=False)


_RULE = "━━━━━━━━━━━━━━"


def _dir_icon(direction: str) -> str:
    return "🟢" if direction.upper() == "CALL" else "🔴"


def _cycle_id(signal: Signal, entry_utc: datetime) -> str:
    """
    Identidad de un ciclo: source+par+entradaZ+dir+expiracion. Unica por entrada; base del dedup
    anti-doble-trade. Incluye source y M{dur} para que el MISMO par/hora en dos proveedores, o en
    la lista M1 y la M5 del mismo proveedor, sean ciclos DISTINTOS (no se pisen en el dedup).
    """
    return (
        f"{signal.source}-{signal.par.replace('/', '')}-"
        f"{entry_utc.strftime('%Y%m%dT%H%M%SZ')}-{signal.direction}-M{signal.duration_min}"
    )


async def notify(text: str) -> None:
    """Envia por Telegram (HTML) sin bloquear el loop (notifier.send es sincrono)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: notifier.send(text, parse_mode="HTML"))


async def sleep_until(target_utc: datetime) -> None:
    """Duerme hasta target_utc, despertando cada <=30s (robusto a drift y a sleeps largos)."""
    while True:
        s = scheduler.seconds_until(target_utc)
        if s <= 0:
            return
        await asyncio.sleep(min(s, 30.0))


# ----------------------------------------------------------------------
#  Circuit breaker (§5) — preparado, apagado por defecto (STOP_LOSS_BALANCE=None)
# ----------------------------------------------------------------------
async def breaker_tripped(broker: broker_mod.IQClient) -> bool:
    if config.STOP_LOSS_BALANCE is None:
        return False
    try:
        bal = await broker.get_balance()
    except Exception as exc:  # noqa: BLE001
        logger.log_error("breaker.balance", exc)
        return False  # ante duda de lectura, no frenar por un fallo de red puntual
    if bal < config.STOP_LOSS_BALANCE:
        await notify(
            f"⛔ <b>Circuit breaker</b>\n{_RULE}\n"
            f"Balance {_money(bal)} &lt; límite {_money(config.STOP_LOSS_BALANCE)}\n"
            f"Operativa detenida."
        )
        return True
    return False


# ----------------------------------------------------------------------
#  Ejecucion de un nivel
# ----------------------------------------------------------------------
async def execute_level(
    broker: broker_mod.IQClient,
    iq_symbol: str,
    signal: Signal,
    level: int,
    prior_losses: Decimal,
    entry_stake: Decimal,
) -> tuple[broker_mod.Settlement, Decimal, Decimal] | None:
    """
    Dimensiona, compra y liquida un nivel. Devuelve (settlement, stake, payout_fraction)
    o None si no se pudo operar (mercado cerrado / error). Recalcula el stake con el
    payout REAL de la proposal (§4.3).
    """
    contract_type = signal.iq_contract_type

    # Mercado abierto a la hora del nivel (§6) — puede haber cerrado entre la entrada y un Gale.
    status = await broker.check_symbol(iq_symbol)
    if not status.exists or not status.is_open:
        motivo = "Mercado No Encontrado / No Disponible" if not status.exists else "Mercado cerrado"
        await notify(
            f"🚫 <b>{motivo}</b> · {_tag(signal.source)}\n{_RULE}\n"
            f"{_level_name(level)} · <b>{signal.par}</b> {signal.direction}\n"
            f"No se opera este nivel."
        )
        logger.log_error("execute_level", f"{motivo}: {iq_symbol} nivel {level}")
        return None

    dur = signal.duration_min

    # Dimensionado (stake de entrada por bucket; el Gale se dimensiona sobre ese stake):
    if level == 0:
        stake = entry_stake
    else:
        # Probe para leer la fraccion de payout real antes de dimensionar el Gale.
        probe = await broker.get_proposal(iq_symbol, contract_type, entry_stake, dur)
        stake = gale.compute_stake(level, prior_losses, probe.payout_fraction, initial_stake=entry_stake)

    # Proposal definitiva al stake calculado -> ask_price y payout reales de ESTE contrato.
    proposal = await broker.get_proposal(iq_symbol, contract_type, stake, dur)
    frac = proposal.payout_fraction

    await notify(
        f"▶️ <b>{_level_name(level)}</b> · {_tag(signal.source)}\n{_RULE}\n"
        f"{_dir_icon(signal.direction)} <b>{signal.par}</b> {signal.direction} · M{dur}\n"
        f"Apuesta <b>{_money(stake)}</b> · Payout {frac:.2f} · Costo {_money(proposal.ask_price)}"
    )

    settlement = await broker.buy_and_settle(proposal)
    return settlement, stake, frac


# ----------------------------------------------------------------------
#  Ciclo completo (entrada + Gale 1 + Gale 2)
# ----------------------------------------------------------------------
async def run_cycle(
    broker: broker_mod.IQClient, signal: Signal, sched: scheduler.Schedule, provider: Provider,
) -> None:
    iq_symbol = broker_mod.to_iq_symbol(signal.par)
    entry_utc = sched.run_times_utc[0]
    cycle_id = _cycle_id(signal, entry_utc)

    # Stake y bucket segun el PROVEEDOR (plano en los nuevos; por par en 'main'). ATR en la entrada (§3).
    entry_stake = provider.stake_for(signal.par)
    bucket = provider.bucket_for(signal.par)
    max_gale = provider.max_gale
    atr_val = float("nan")

    prior_losses = Decimal("0")
    resolved_level: int | None = None
    cycle_result = "loss"
    net = Decimal("0")
    balance_after: Decimal | None = None

    for level in range(max_gale + 1):
        run_at = sched.run_times_utc[level]
        await sleep_until(run_at)

        if await breaker_tripped(broker):
            await notify(
                f"⛔ <b>Ciclo abortado</b> · {_tag(signal.source)}\n{_RULE}\n"
                f"<b>{signal.par}</b> · circuit breaker en {_level_name(level)}."
            )
            logger.log_error("run_cycle", f"breaker abort {cycle_id} nivel {level}")
            return

        # Filtro de tendencia (§ grupos: "no opere contra tendencia"). Se mide EN LA ENTRADA
        # (nivel 0), con la TF de la senal. Si la senal va contra el trend -> no se opera el ciclo.
        # Si no se puede medir (None) -> se opera igual (no bloquear por falta de datos).
        if level == 0 and provider.trend_filter:
            interval = signal.duration_min * 60
            tdir = await broker.get_trend(iq_symbol, interval, config.TREND_EMA_FAST, config.TREND_EMA_SLOW)
            if tdir is not None and tdir != signal.direction:
                await notify(
                    f"🧭 <b>Filtrada por tendencia</b> · {_tag(signal.source)}\n{_RULE}\n"
                    f"<b>{signal.par}</b> {signal.direction} M{signal.duration_min} va "
                    f"CONTRA tendencia (mercado {tdir}).\nNo se opera."
                )
                logger.log_cycle(
                    cycle_id=cycle_id, par=signal.par, direction=signal.direction,
                    resolved_at_level=None, cycle_result="skipped", net=Decimal("0"),
                    balance_after=None,
                )
                return

        # Ejecuta el nivel con un reintento via reconexion ante error puntual (§7).
        outcome = None
        for attempt in (1, 2):
            try:
                outcome = await execute_level(broker, iq_symbol, signal, level, prior_losses, entry_stake)
                break
            except Exception as exc:  # noqa: BLE001 - logueamos y reintentamos una vez
                logger.log_error(f"run_cycle.execute.attempt{attempt}", exc)
                if attempt == 1:
                    await broker.reconnect()
                else:
                    await notify(
                        f"❌ <b>Error en {_level_name(level)}</b> · {_tag(signal.source)}\n{_RULE}\n"
                        f"<b>{signal.par}</b> · nivel no operado tras reintento."
                    )

        if outcome is None:
            # No se pudo operar este nivel (mercado cerrado / error persistente).
            if level == 0:
                # Entrada fallida -> no se entra a ningun nivel del ciclo (§6).
                logger.log_cycle(
                    cycle_id=cycle_id, par=signal.par, direction=signal.direction,
                    resolved_at_level=None, cycle_result="skipped", net=Decimal("0"),
                    balance_after=balance_after,
                )
                return
            # Gale fallido -> no se puede recuperar; el ciclo cierra en perdida con lo ya perdido.
            break

        settlement, stake, frac = outcome

        # ATR de la entrada (dato crudo para el test de volatilidad §3). No rompe el ciclo si falla.
        if level == 0:
            atr_val = await broker.get_atr(iq_symbol)

        try:
            balance_after = await broker.get_balance()
        except Exception as exc:  # noqa: BLE001
            logger.log_error("run_cycle.balance", exc)
            balance_after = None

        logger.log_level(
            cycle_id=cycle_id, par=signal.par, iq_symbol=iq_symbol,
            direction=signal.direction, level=level, stake=stake, payout_fraction=frac,
            entry_spot=settlement.entry_spot, exit_spot=settlement.exit_spot,
            result=settlement.result, contract_id=settlement.contract_id,
            balance_after=balance_after,
        )

        if settlement.result == "won":
            profit = settlement.profit if settlement.profit is not None else (stake * frac)
            net = profit - prior_losses
            resolved_level = level
            cycle_result = "win"
            await notify(
                f"✅ <b>GANO</b> · {_level_name(level)} · {_tag(signal.source)}\n{_RULE}\n"
                f"<b>{signal.par}</b> {signal.direction} M{signal.duration_min}\n"
                f"Ganancia <b>{_money(profit)}</b> · Neto ciclo <b>{_money(net)}</b>\n"
                f"💰 Balance {_money(balance_after)}"
            )
            break
        else:
            prior_losses += stake
            net = -prior_losses
            await notify(
                f"🔴 <b>PERDIO</b> · {_level_name(level)} · {_tag(signal.source)}\n{_RULE}\n"
                f"<b>{signal.par}</b> {signal.direction} M{signal.duration_min}\n"
                f"Perdió {_money(stake)} · Acumulado <b>{_money(prior_losses)}</b>"
            )

    # Cierre de ciclo (§8)
    logger.log_cycle(
        cycle_id=cycle_id, par=signal.par, direction=signal.direction,
        resolved_at_level=resolved_level, cycle_result=cycle_result, net=net,
        balance_after=balance_after,
    )

    # Log de recoleccion: 1 fila/ciclo con bucket, stake, outcome, ATR y pnl (§4 handoff).
    if cycle_result == "win":
        outcome_str = "WIN_DIRECTO" if resolved_level == 0 else "WIN_GALE"
    else:
        outcome_str = "LOSS"
    gale_resuelto = resolved_level if resolved_level is not None else max_gale
    logger.log_entry(
        timestamp=entry_utc.isoformat(), cycle_id=cycle_id, par=signal.par, bucket=bucket,
        stake_usado=entry_stake, gale_level_resuelto=gale_resuelto, outcome=outcome_str,
        atr_14_5m=atr_val, pnl_ciclo=net,
    )

    icon = "✅" if cycle_result == "win" else "🟥"
    if resolved_level is not None:
        where = _level_name(resolved_level)
    else:
        where = "perdido" if max_gale == 0 else f"perdido (Gale {max_gale})"
    await notify(
        f"{icon} <b>Ciclo cerrado</b> · {_tag(signal.source)}\n{_RULE}\n"
        f"<b>{signal.par}</b> {signal.direction} M{signal.duration_min}\n"
        f"Resultado: <b>{cycle_result.upper()} en {where}</b>\n"
        f"Neto <b>{_money(net)}</b> · 💰 Balance {_money(balance_after)}"
    )


# ----------------------------------------------------------------------
#  Manejo de cada mensaje del canal
# ----------------------------------------------------------------------
async def handle_message(text: str, chat_id: int, broker: broker_mod.IQClient) -> None:
    """
    Enruta el mensaje a su proveedor (por chat_id), parsea 0..N senales (los canales de lista
    diaria traen muchas en un solo mensaje) y programa cada una con los parametros del proveedor
    (TZ, niveles de Gale, stake, expiracion M1/M5).
    """
    provider = providers.provider_for(chat_id)
    if provider is None:
        return  # mensaje de un chat no registrado -> ignorar

    try:
        signals = provider.parse(text)
        if not signals:
            return  # ninguna senal en el mensaje -> ignorar (headers, motivacionales, recaps)

        for signal in signals:
            await _schedule_one(signal, provider, broker)

    except Exception as exc:  # noqa: BLE001 - nunca tragar (§14)
        logger.log_error("handle_message", exc)
        await notify(
            f"❌ <b>Error procesando mensaje</b> · {_tag(provider.key)}\n{_RULE}\n"
            f"<code>{_esc(repr(exc))}</code>"
        )


async def _schedule_one(signal: Signal, provider: Provider, broker: broker_mod.IQClient) -> None:
    """Programa UNA senal (usado por cada entrada de una lista diaria o senal en vivo)."""
    # Mercado deshabilitado por politica de stake (STAKE_TABLE par=0.00): no operar, solo loguear.
    if provider.stake_for(signal.par) <= 0:
        logger.log_error("schedule.market_off", f"[{provider.key}] {signal.par}: stake 0 (mercado deshabilitado)")
        return

    sched = scheduler.build_schedule(
        signal, tz=provider.tz, max_levels=provider.max_gale, step_minutes=signal.duration_min,
    )

    if sched.skipped:
        # En listas diarias muchas entradas ya vencieron: no spamear Telegram, solo loguear.
        logger.log_error("schedule.skip", f"[{provider.key}] {signal.par} {signal.entry_hhmm}: {sched.reason}")
        return

    # Anti-doble-trade: los canales EDITAN sus mensajes (meten resultados), asi que la misma
    # entrada llega varias veces (edicion + polling). Reclamamos la identidad del ciclo ANTES de
    # avisar/operar; si ya estaba reclamada, salimos en silencio.
    cycle_id = _cycle_id(signal, sched.run_times_utc[0])
    if not _claim_cycle(cycle_id):
        return

    # Pre-chequeo de disponibilidad del mercado AL RECIBIR (§6): feedback inmediato.
    iq_symbol = broker_mod.to_iq_symbol(signal.par)
    try:
        status = await broker.check_symbol(iq_symbol)
    except Exception as exc:  # noqa: BLE001 - hipo de red: no bloquear, se revalida en la entrada
        logger.log_error("schedule.check_symbol", exc)
        status = None

    if status is not None and not status.exists:
        await notify(
            f"🚫 <b>Mercado No Encontrado / No Disponible</b> · {_tag(provider.key)}\n{_RULE}\n"
            f"<b>{signal.par}</b> ({_esc(iq_symbol)})\nNo se opera esta senal."
        )
        logger.log_error("schedule.symbol", f"[{provider.key}] No encontrado: {signal.par} ({iq_symbol})")
        return

    if status is not None and not status.is_open:
        await notify(
            f"⏸️ <b>Mercado cerrado ahora</b> · {_tag(provider.key)}\n{_RULE}\n"
            f"<b>{signal.par}</b> · se revalida a la hora de entrada."
        )

    gale_txt = "sin gale" if provider.max_gale == 0 else f"{provider.max_gale} gale"
    await notify(
        f"📩 <b>Señal programada</b> · {_tag(provider.key)}\n{_RULE}\n"
        f"{_dir_icon(signal.direction)} <b>{signal.par}</b> {signal.direction} · M{signal.duration_min}\n"
        f"🕐 Entrada <b>{sched.entry_local_display.strftime('%H:%M')}</b> (Colombia)\n"
        f"💵 Stake <b>{_money(provider.stake_for(signal.par))}</b> · {gale_txt}"
    )

    # Ejecuta el ciclo en su propia task para no bloquear al listener.
    asyncio.create_task(run_cycle(broker, signal, sched, provider))


# ----------------------------------------------------------------------
#  Dedup entre el handler en vivo y el polling fallback
# ----------------------------------------------------------------------
# Estado del texto ya procesado por id. NO basta dedup por id solo: el canal EDITA sus mensajes
# (mete el par o corrige un typo tras postear), y si ignoramos la edicion el bot se queda con la
# primera version. Guardamos hash(texto): reprocesamos un id SOLO si su texto cambio (= edicion).
# Asyncio es de un solo hilo: el check+set antes del primer await es atomico, no hay doble proceso.
# Clave (chat_id, msg_id): el id de mensaje es unico POR CHAT, no global entre canales.
_seen_text: dict[tuple[int, int], int] = {}

# Identidades de ciclo ya programadas (source+par+entradaZ+dir+M). Una edicion re-procesada vuelve
# a llegar como senal valida; este set evita programar/operar el MISMO ciclo dos veces.
_scheduled_cycles: set[str] = set()


def _remember(chat_id: int, msg_id: int, text: str) -> bool:
    """True la PRIMERA vez que vemos el (chat,id) O si su texto cambio (edicion); marca el estado."""
    key = (chat_id, msg_id)
    h = hash(text)
    if _seen_text.get(key) == h:
        return False
    _seen_text[key] = h
    # Cota de memoria: si crece mucho, recortamos los viejos.
    if len(_seen_text) > 5000:
        for old in sorted(_seen_text)[:2500]:
            _seen_text.pop(old, None)
    return True


def _claim_cycle(cycle_id: str) -> bool:
    """True si es la PRIMERA vez que se programa este ciclo (y lo reclama). False si ya estaba."""
    if cycle_id in _scheduled_cycles:
        return False
    _scheduled_cycles.add(cycle_id)
    if len(_scheduled_cycles) > 5000:
        for old in sorted(_scheduled_cycles)[:2500]:
            _scheduled_cycles.discard(old)
    return True


async def process_message(text: str, msg_id: int, chat_id: int, broker: broker_mod.IQClient) -> None:
    """Punto unico de entrada (vivo + polling). Reprocesa solo si el (chat,id) es nuevo o su texto cambio."""
    if not _remember(chat_id, msg_id, text):
        return
    await handle_message(text, chat_id, broker)


# ----------------------------------------------------------------------
#  Polling fallback (§ robustez): si telethon se cae, NO perdemos senales.
# ----------------------------------------------------------------------
async def poll_channel(client, broker: broker_mod.IQClient) -> None:
    """
    Cada POLL_INTERVAL_SECONDS relee los ultimos POLL_LIMIT mensajes de CADA canal registrado y
    procesa los que el handler en vivo se haya perdido (desconexion) Y las ediciones que cambiaron
    el texto (get_messages devuelve la version actual). Dedup por (chat,id)+texto via process_message.
    """
    refs = providers.all_channel_ids()
    while True:
        for ref in refs:
            try:
                msgs = await client.get_messages(ref, limit=config.POLL_LIMIT)
                # get_messages devuelve del mas nuevo al mas viejo -> procesar en orden cronologico.
                for m in reversed(msgs):
                    text = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
                    mid = int(m.id)
                    cid = int(getattr(m, "chat_id", None) or ref)
                    if text:
                        await process_message(text, mid, cid, broker)
            except Exception as exc:  # noqa: BLE001 - el watchdog nunca debe morir
                logger.log_error("poll_channel", f"canal {ref}: {exc!r}")
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)


# ----------------------------------------------------------------------
#  Keep-alive de IQ Option (§ robustez): la lib pierde el ws seguido.
# ----------------------------------------------------------------------
async def iq_keepalive(broker: broker_mod.IQClient) -> None:
    """Cada IQ_KEEPALIVE_SECONDS verifica la conexion IQ y reconecta si cayo. Avisa al recuperar."""
    was_down = False
    while True:
        try:
            ok = await broker.ensure_connected()
            if not ok and not was_down:
                was_down = True
                await notify(
                    f"⚠️ <b>IQ Option desconectado</b>\n{_RULE}\nReintentando reconexión en background…"
                )
                logger.log_error("iq_keepalive", "IQ caido, reconectando")
            elif ok and was_down:
                was_down = False
                await notify(f"🔌 <b>IQ Option reconectado</b>\n{_RULE}\nOperativa restaurada.")
        except Exception as exc:  # noqa: BLE001 - el watchdog nunca debe morir
            logger.log_error("iq_keepalive", exc)
        await asyncio.sleep(config.IQ_KEEPALIVE_SECONDS)


# ----------------------------------------------------------------------
#  Arranque
# ----------------------------------------------------------------------
async def amain() -> None:
    config.validate()
    print(config.summary())

    broker = broker_mod.IQClient()
    await broker.connect()

    canales = " · ".join(p.key.upper() for p in providers.REGISTRY.values())
    try:
        bal = await broker.get_balance()
        await notify(
            f"🟢 <b>Bot iniciado</b>\n{_RULE}\n"
            f"Copy-trade IQ Option · turbo\n"
            f"📡 Canales: {canales}\n"
            f"💰 Balance {_money(bal)}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.log_error("amain.balance", exc)
        await notify(
            f"🟢 <b>Bot iniciado</b>\n{_RULE}\n"
            f"📡 Canales: {canales}\n"
            f"⚠️ No se pudo leer balance inicial (ver errors.log)."
        )

    client = build_client(lambda t, mid, cid: process_message(t, mid, cid, broker))
    await client.start()
    me = await client.get_me()
    print(f"Telethon conectado como: {getattr(me, 'username', None) or getattr(me, 'id', '?')}")
    # Cargar dialogos cachea las entidades (incl. los canales con su access_hash). Sin esto,
    # el handler con chats=-100... falla con "Cannot find any entity corresponding to ...".
    await client.get_dialogs()

    # Seed: marcar el backlog actual de CADA canal como YA VISTO para no re-accionar senales
    # viejas al arrancar. A partir de aqui solo se acciona lo NUEVO; el polling cubre huecos.
    for ref, prov in providers.REGISTRY.items():
        if not prov.seed_on_start:
            # Canales de lista diaria: NO sembrar -> el poll procesa la lista de HOY.
            print(f"Canal {prov.key}({ref}): sin seed (procesa lista de hoy via poll).")
            continue
        try:
            backlog = await client.get_messages(ref, limit=config.POLL_LIMIT)
            for m in backlog:
                text = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
                cid = int(getattr(m, "chat_id", None) or ref)
                _remember(cid, int(m.id), text)
            print(f"Backlog sembrado canal {prov.key}({ref}): {len(backlog)} mensajes.")
        except Exception as exc:  # noqa: BLE001
            logger.log_error("amain.seed_backlog", f"canal {ref}: {exc!r}")

    escuchando = ", ".join(f"{p.key}({cid})" for cid, p in providers.REGISTRY.items())
    print(f"Escuchando canales: {escuchando}")

    # Watchdogs: polling de respaldo (cero senales perdidas) + keep-alive de IQ.
    poll_task = asyncio.create_task(poll_channel(client, broker))
    keep_task = asyncio.create_task(iq_keepalive(broker))

    try:
        await client.run_until_disconnected()
    finally:
        poll_task.cancel()
        keep_task.cancel()
        await broker.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
