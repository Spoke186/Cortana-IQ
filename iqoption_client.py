"""
iqoption_client.py — cliente IQ Option (turbo options 5 min). Unico broker del bot.

POR QUE IQ (verificado en vivo 2026-06):
  - IQ Option ofrece TURBO (1-5 min) sobre todos los pares, incluidos exoticos
    (USDTRY, USDIDR) como variante "-OTC" en fin de semana. Es el 5 min que pide la senal.
  - Las DIGITAL options de la lib iqoptionapi estan ROTAS contra el backend actual
    ("GetUnderlyingList V2 is not supported"), asi que se usa TURBO, no digital.

Interfaz async: clase IQClient con check_symbol / get_proposal / buy_and_settle, y la
funcion to_iq_symbol. main.py la consume directamente.

ASYNC: iqoptionapi es SINCRONA y bloqueante (maneja su propio ws en hilos). Cada llamada
se envuelve en run_in_executor para no bloquear el loop de asyncio de main.py.

OTC vs real (IMPORTANTE): en fin de semana / mercado cerrado solo abre la variante "-OTC",
que tiene PRECIO SINTETICO de IQ, no el mercado real en que se basa la senal del canal.
Copiar senales sobre -OTC no rastrea el subyacente real. El bot opera lo que este abierto
y lo deja registrado; la decision de operar finde es de Esteban (ver README).

Mapeo de resultado: IQ devuelve 'win'|'loose'|'equal'. Se mapea won|lost; 'equal' (empate,
devuelve stake) se trata como won con profit 0 y se loguea.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.constants as OP_code

import config
import logger


# La lib lanza KeyError('underlying') en su hilo de digital options (GetUnderlyingList V2 no
# soportado por el backend actual). Usamos TURBO, no digital -> silenciamos SOLO ese ruido de
# hilo para no ensuciar stderr en cada get_all_open_time. Cualquier otra excepcion se respeta.
_prev_excepthook = threading.excepthook


def _quiet_digital_hook(args):
    if args.exc_type is KeyError and "underlying" in str(args.exc_value):
        return
    _prev_excepthook(args)


threading.excepthook = _quiet_digital_hook


# ----------------------------------------------------------------------
#  Mapeo de simbolos
# ----------------------------------------------------------------------
def to_iq_symbol(par: str) -> str:
    """'EUR/JPY' -> 'EURJPY' (base IQ; la variante -OTC se resuelve segun apertura)."""
    return par.replace("/", "").upper()


def _candidates(base: str) -> list[str]:
    """Prefiere el par real; cae a -OTC (fin de semana). Ambos deben existir en las constantes."""
    return [c for c in (base, f"{base}-OTC") if c in OP_code.ACTIVES]


# ----------------------------------------------------------------------
#  Dataclasses
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class SymbolStatus:
    exists: bool
    is_open: bool


@dataclass(frozen=True)
class Proposal:
    id: str                 # asset IQ resuelto (ej. 'EURUSD-OTC'); IQ no tiene proposal-id
    ask_price: Decimal      # costo = stake (turbo: pagas el stake)
    payout: Decimal         # retorno BRUTO si gana = stake * (1 + fraccion)
    spot: Decimal | None    # IQ turbo no expone spot en este paso -> None
    # extras IQ para que buy_and_settle tenga todo:
    asset: str = ""
    action: str = ""        # 'call' | 'put'
    stake: Decimal = Decimal("0")

    @property
    def payout_fraction(self) -> Decimal:
        """Fraccion de GANANCIA = (bruto - costo)/costo (ej. 0.87)."""
        if self.ask_price <= 0:
            raise ValueError("ask_price <= 0 en proposal")
        return (self.payout - self.ask_price) / self.ask_price


@dataclass(frozen=True)
class Settlement:
    contract_id: str
    result: str             # "won" | "lost"
    entry_spot: Decimal | None
    exit_spot: Decimal | None
    profit: Decimal | None  # neto del contrato (positivo gano, negativo perdio)
    buy_price: Decimal | None


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


# ----------------------------------------------------------------------
#  Cliente
# ----------------------------------------------------------------------
class IQClient:
    def __init__(self) -> None:
        self.iq: IQ_Option | None = None

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *args)

    # ---- conexion -----------------------------------------------------
    def _connect_sync(self) -> IQ_Option:
        iq = IQ_Option(config.IQ_EMAIL, config.IQ_PASSWORD)
        check, reason = iq.connect()
        if not check:
            raise RuntimeError(f"Login IQ fallo: {reason!r}")
        mode = "REAL" if config.IQ_ACCOUNT_TYPE.lower() == "real" else "PRACTICE"
        iq.change_balance(mode)
        return iq

    async def connect(self) -> None:
        self.iq = await self._run(self._connect_sync)

    async def reconnect(self) -> None:
        logger.log_error("iq.reconnect", "reconectando IQ Option")
        try:
            self.iq = await self._run(self._connect_sync)
        except Exception as exc:  # noqa: BLE001 - logueamos, no tragamos
            logger.log_error("iq.reconnect.fail", exc)
            raise

    async def disconnect(self) -> None:
        # iqoptionapi no expone un close limpio; soltamos la referencia.
        self.iq = None

    # ---- lecturas -----------------------------------------------------
    async def get_balance(self) -> Decimal:
        assert self.iq is not None
        bal = await self._run(self.iq.get_balance)
        return Decimal(str(bal))

    def _resolve_sync(self, base: str) -> tuple[bool, str | None]:
        """(existe_en_IQ, asset_abierto_o_None). Prefiere par real, cae a -OTC."""
        cands = _candidates(base)
        if not cands:
            return False, None
        ot = self.iq.get_all_open_time()  # type: ignore[union-attr]
        turbo = ot.get("turbo", {})
        for c in cands:
            if turbo.get(c, {}).get("open"):
                return True, c
        return True, None  # existe pero ninguno abierto ahora

    async def check_symbol(self, iq_symbol: str) -> SymbolStatus:
        assert self.iq is not None
        exists, asset = await self._run(self._resolve_sync, iq_symbol)
        return SymbolStatus(exists=exists, is_open=asset is not None)

    def _profit_fraction_sync(self, asset: str) -> Decimal:
        prof = self.iq.get_all_profit()  # type: ignore[union-attr]
        frac = prof.get(asset, {}).get("turbo")
        if frac in (None, 0, 0.0):
            raise RuntimeError(f"payout turbo no disponible para {asset}: {frac!r}")
        return Decimal(str(frac))

    async def get_proposal(self, iq_symbol: str, contract_type: str, amount: Decimal) -> Proposal:
        """
        IQ no tiene 'proposal'. Sintetiza una: resuelve el asset abierto, lee el payout REAL
        de turbo (fraccion, ej. 0.87) y arma costo=stake / bruto=stake*(1+frac).
        """
        assert self.iq is not None
        exists, asset = await self._run(self._resolve_sync, iq_symbol)
        if not exists or asset is None:
            raise RuntimeError(f"asset no disponible/cerrado: {iq_symbol}")
        frac = await self._run(self._profit_fraction_sync, asset)
        action = "call" if contract_type.upper() == "CALL" else "put"
        ask = amount
        payout = (amount * (Decimal("1") + frac))
        return Proposal(
            id=asset, ask_price=ask, payout=payout, spot=None,
            asset=asset, action=action, stake=amount,
        )

    # ---- compra + liquidacion ----------------------------------------
    def _buy_and_wait_sync(self, asset: str, action: str, stake: float, timeout_s: float) -> dict:
        iq = self.iq
        assert iq is not None
        if asset not in OP_code.ACTIVES:
            raise RuntimeError(f"asset desconocido en constantes IQ: {asset}")
        ok, order_id = iq.buy(stake, asset, action, config.CONTRACT_DURATION)
        if not ok or order_id is None:
            raise RuntimeError(f"buy IQ rechazado: asset={asset} action={action} id={order_id!r}")

        # Espera el cierre con timeout propio (check_win_v4 hace while True sin timeout).
        deadline = time.time() + timeout_s
        closed = iq.api.socket_option_closed
        while time.time() < deadline:
            x = closed.get(order_id)
            if x is not None:
                msg = x["msg"]
                win = msg["win"]                      # 'win' | 'loose' | 'equal'
                total = float(msg["sum"])
                if win == "equal":
                    profit = 0.0
                elif win == "loose":
                    profit = -total
                else:
                    profit = float(msg["win_amount"]) - total
                return {"order_id": order_id, "win": win, "profit": profit, "msg": msg}
            time.sleep(1.0)
        raise TimeoutError(f"timeout esperando cierre del contrato {order_id} ({asset})")

    async def buy_and_settle(self, proposal: Proposal, *, timeout_s: float | None = None) -> Settlement:
        assert self.iq is not None
        if timeout_s is None:
            timeout_s = config.CONTRACT_DURATION * 60 + 120  # contrato + margen de settlement
        r = await self._run(
            self._buy_and_wait_sync, proposal.asset, proposal.action,
            float(proposal.stake), timeout_s,
        )
        win = r["win"]
        if win == "win":
            result = "won"
        elif win == "loose":
            result = "lost"
        else:  # 'equal' (empate) -> stake devuelto; lo tratamos como won 0 y logueamos.
            result = "won"
            logger.log_error("iq.settle.equal", f"empate en {proposal.asset} id {r['order_id']}")
        return Settlement(
            contract_id=str(r["order_id"]),
            result=result,
            entry_spot=None,   # IQ turbo no entrega spots de entrada/cierre por esta via
            exit_spot=None,
            profit=_dec(r["profit"]),
            buy_price=proposal.stake,
        )
