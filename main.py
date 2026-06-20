"""
main.py — orquesta: listener -> parser -> scheduler -> broker(IQ) -> gale -> notifier -> logger. (§10, §13.7)

Modo: copy trade puro sobre IQ Option (turbo 5min). El bot NO decide nada de trading;
obedece la senal (§0).
"""
from __future__ import annotations

import asyncio
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
import scheduler
from listener import build_client
from parser import Signal, parse_signal

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


async def notify(text: str) -> None:
    """Envia por Telegram sin bloquear el loop (notifier.send es sincrono)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, notifier.send, text)


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
        await notify(f"⛔ Circuit breaker: balance {_money(bal)} < {_money(config.STOP_LOSS_BALANCE)}. No se opera.")
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
        await notify(f"🚫 {_level_name(level)} {signal.par}: {motivo}. No se opera este nivel (§6).")
        logger.log_error("execute_level", f"{motivo}: {iq_symbol} nivel {level}")
        return None

    # Dimensionado:
    if level == 0:
        stake = config.INITIAL_STAKE
    else:
        # Probe para leer la fraccion de payout real antes de dimensionar el Gale.
        probe = await broker.get_proposal(iq_symbol, contract_type, config.INITIAL_STAKE)
        stake = gale.compute_stake(level, prior_losses, probe.payout_fraction)

    # Proposal definitiva al stake calculado -> ask_price y payout reales de ESTE contrato.
    proposal = await broker.get_proposal(iq_symbol, contract_type, stake)
    frac = proposal.payout_fraction

    await notify(
        f"▶️ {_level_name(level)} {signal.par} {signal.direction}\n"
        f"Apuesta: {_money(stake)} | Payout real: {frac:.4f} | Costo: {_money(proposal.ask_price)}"
    )

    settlement = await broker.buy_and_settle(proposal)
    return settlement, stake, frac


# ----------------------------------------------------------------------
#  Ciclo completo (entrada + Gale 1 + Gale 2)
# ----------------------------------------------------------------------
async def run_cycle(broker: broker_mod.IQClient, signal: Signal, sched: scheduler.Schedule) -> None:
    iq_symbol = broker_mod.to_iq_symbol(signal.par)
    entry_utc = sched.run_times_utc[0]
    cycle_id = f"{signal.par.replace('/', '')}-{entry_utc.strftime('%Y%m%dT%H%M%SZ')}-{signal.direction}"

    prior_losses = Decimal("0")
    resolved_level: int | None = None
    cycle_result = "loss"
    net = Decimal("0")
    balance_after: Decimal | None = None

    for level in range(config.MAX_GALE_LEVELS + 1):
        run_at = sched.run_times_utc[level]
        await sleep_until(run_at)

        if await breaker_tripped(broker):
            await notify(f"Ciclo {signal.par} abortado por circuit breaker en {_level_name(level)}.")
            logger.log_error("run_cycle", f"breaker abort {cycle_id} nivel {level}")
            return

        # Ejecuta el nivel con un reintento via reconexion ante error puntual (§7).
        outcome = None
        for attempt in (1, 2):
            try:
                outcome = await execute_level(broker, iq_symbol, signal, level, prior_losses)
                break
            except Exception as exc:  # noqa: BLE001 - logueamos y reintentamos una vez
                logger.log_error(f"run_cycle.execute.attempt{attempt}", exc)
                if attempt == 1:
                    await broker.reconnect()
                else:
                    await notify(f"❌ {_level_name(level)} {signal.par}: error tras reintento. Nivel no operado.")

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
                f"✅ {_level_name(level)} {signal.par}: GANO. "
                f"Ganancia nivel {_money(profit)} | Neto ciclo {_money(net)} | Balance {_money(balance_after)}"
            )
            break
        else:
            prior_losses += stake
            net = -prior_losses
            await notify(
                f"🔴 {_level_name(level)} {signal.par}: PERDIO {_money(stake)}. "
                f"Perdido acumulado {_money(prior_losses)}."
            )

    # Cierre de ciclo (§8)
    logger.log_cycle(
        cycle_id=cycle_id, par=signal.par, direction=signal.direction,
        resolved_at_level=resolved_level, cycle_result=cycle_result, net=net,
        balance_after=balance_after,
    )
    icon = "✅" if cycle_result == "win" else "🟥"
    where = _level_name(resolved_level) if resolved_level is not None else "perdido (Gale 2)"
    await notify(
        f"{icon} Ciclo {signal.par} {signal.direction} cerrado: {cycle_result.upper()} en {where}.\n"
        f"Neto: {_money(net)} | Balance: {_money(balance_after)}"
    )


# ----------------------------------------------------------------------
#  Manejo de cada mensaje del canal
# ----------------------------------------------------------------------
async def handle_message(text: str, broker: broker_mod.IQClient) -> None:
    try:
        signal = parse_signal(text)
        if signal is None:
            return  # no es senal de entrada -> ignorar (§1.2)

        sched = scheduler.build_schedule(signal)

        if sched.skipped:
            await notify(f"⏭️ Senal {signal.par} {signal.direction} saltada: {sched.reason}")
            logger.log_error("handle_message.skip", sched.reason)
            return

        if sched.gale_mismatch:
            logger.log_error(
                "handle_message.gale_mismatch",
                f"horas Gale declaradas {signal.declared_gale_hhmm} no cuadran con derivadas; uso derivadas",
            )

        # Pre-chequeo de disponibilidad del mercado AL RECIBIR la senal (§6): feedback inmediato.
        # Si el par no existe en IQ -> avisar "Mercado No Encontrado / No Disponible" y NO programar.
        iq_symbol = broker_mod.to_iq_symbol(signal.par)
        try:
            status = await broker.check_symbol(iq_symbol)
        except Exception as exc:  # noqa: BLE001 - hipo de red puntual: no bloquear, se revalida en la entrada
            logger.log_error("handle_message.check_symbol", exc)
            status = None

        if status is not None and not status.exists:
            await notify(
                f"🚫 Mercado No Encontrado / No Disponible: {signal.par} ({iq_symbol}). "
                f"No se opera esta senal (§6)."
            )
            logger.log_error("handle_message.symbol", f"Mercado No Encontrado: {signal.par} ({iq_symbol})")
            return

        if status is not None and not status.is_open:
            await notify(
                f"⏸️ Mercado cerrado ahora: {signal.par} ({iq_symbol}). "
                f"Se revalida a la hora de entrada; si sigue cerrado, no se opera."
            )

        # Aviso: senal recibida y programada (hora Colombia + UTC-3) (§8)
        await notify(
            f"📩 Senal {signal.par} {signal.direction} programada.\n"
            f"Entrada {sched.entry_local_display.strftime('%H:%M')} (Colombia) / "
            f"{sched.entry_local_signal.strftime('%H:%M')} (UTC-3) | Stake {_money(config.INITIAL_STAKE)}"
        )

        # Ejecuta el ciclo en su propia task para no bloquear al listener.
        asyncio.create_task(run_cycle(broker, signal, sched))

    except Exception as exc:  # noqa: BLE001 - nunca tragar (§14)
        logger.log_error("handle_message", exc)
        await notify(f"❌ Error procesando mensaje: {exc!r}")


# ----------------------------------------------------------------------
#  Dedup entre el handler en vivo y el polling fallback
# ----------------------------------------------------------------------
# Ids de mensajes ya vistos (por cualquiera de las dos vias). Asyncio es de un solo hilo:
# el check+add antes del primer await es atomico, asi que no hay doble procesamiento.
_seen_ids: set[int] = set()


def _remember(msg_id: int) -> bool:
    """Devuelve True si es la PRIMERA vez que vemos este id (y lo marca). False si repetido."""
    if msg_id in _seen_ids:
        return False
    _seen_ids.add(msg_id)
    # Cota de memoria: en un dia entran pocos cientos; si crece mucho, recortamos los viejos.
    if len(_seen_ids) > 5000:
        for old in sorted(_seen_ids)[:2500]:
            _seen_ids.discard(old)
    return True


async def process_message(text: str, msg_id: int, broker: broker_mod.IQClient) -> None:
    """Punto unico de entrada (vivo + polling). Deduplica por id antes de accionar."""
    if not _remember(msg_id):
        return
    await handle_message(text, broker)


# ----------------------------------------------------------------------
#  Polling fallback (§ robustez): si telethon se cae, NO perdemos senales.
# ----------------------------------------------------------------------
async def poll_channel(client, broker: broker_mod.IQClient) -> None:
    """
    Cada POLL_INTERVAL_SECONDS relee los ultimos POLL_LIMIT mensajes del canal y procesa
    los que el handler en vivo se haya perdido (desconexion). Dedup por id via process_message.
    """
    from listener import channel_ref
    ref = channel_ref()
    while True:
        try:
            msgs = await client.get_messages(ref, limit=config.POLL_LIMIT)
            # get_messages devuelve del mas nuevo al mas viejo -> procesar en orden cronologico.
            for m in reversed(msgs):
                text = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
                mid = int(m.id)
                if text:
                    await process_message(text, mid, broker)
        except Exception as exc:  # noqa: BLE001 - el watchdog nunca debe morir
            logger.log_error("poll_channel", exc)
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
                await notify("⚠️ IQ Option desconectado. Reintentando reconexion en background...")
                logger.log_error("iq_keepalive", "IQ caido, reconectando")
            elif ok and was_down:
                was_down = False
                await notify("🔌 IQ Option reconectado. Operativa restaurada.")
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

    try:
        bal = await broker.get_balance()
        await notify(f"🟢 Bot iniciado (copy trade IQ Option, turbo 5min). Balance inicial: {_money(bal)}")
    except Exception as exc:  # noqa: BLE001
        logger.log_error("amain.balance", exc)
        await notify("🟢 Bot iniciado (no se pudo leer balance inicial; ver errors.log).")

    client = build_client(lambda t, mid: process_message(t, mid, broker))
    await client.start()
    me = await client.get_me()
    print(f"Telethon conectado como: {getattr(me, 'username', None) or getattr(me, 'id', '?')}")
    # Cargar dialogos cachea las entidades (incl. el canal con su access_hash). Sin esto,
    # el handler con chats=-100... falla con "Cannot find any entity corresponding to ...".
    await client.get_dialogs()

    # Seed: marcar el backlog actual como YA VISTO para no re-accionar senales viejas al
    # arrancar (todas estarian vencidas). A partir de aqui solo se acciona lo NUEVO; el
    # polling fallback cubre cualquier hueco si telethon se cae despues.
    from listener import channel_ref
    try:
        backlog = await client.get_messages(channel_ref(), limit=config.POLL_LIMIT)
        for m in backlog:
            _remember(int(m.id))
        print(f"Backlog sembrado: {len(backlog)} mensajes marcados como vistos.")
    except Exception as exc:  # noqa: BLE001
        logger.log_error("amain.seed_backlog", exc)

    print(f"Escuchando canal: {config.TG_CHANNEL}")

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
