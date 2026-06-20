"""
test_integration.py — orquestacion completa con un broker FALSO (sin credenciales ni dinero).

Confirma SIN tocar la API real:
  - Mercado no encontrado -> mensaje "Mercado No Encontrado / No Disponible" y NO se opera.
  - Mercado cerrado        -> mensaje "Mercado cerrado" y NO se opera ese nivel.
  - Mensaje de ruido       -> nada (ni aviso ni operacion).
  - Win en entrada / Win en Gale / perdida total -> stakes correctos, neto correcto, ciclo logueado.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import config
import main
import scheduler
from iqoption_client import Proposal, Settlement, SymbolStatus
from parser import Signal


# --------------------------------------------------------------------------
#  Broker FALSO
# --------------------------------------------------------------------------
class FakeBroker:
    def __init__(self, *, exists=True, is_open=True, payout="0.90", results=None, balance="100"):
        self.exists = exists
        self.is_open = is_open
        self.payout = Decimal(payout)          # fraccion de ganancia
        self.results = list(results or [])     # "won"/"lost" por nivel
        self.balance = Decimal(balance)
        self.bought: list[Decimal] = []         # stake comprado por nivel (solo finales)
        self._i = 0

    async def connect(self): ...
    async def disconnect(self): ...
    async def reconnect(self): ...

    async def get_balance(self):
        return self.balance

    async def check_symbol(self, sym):
        return SymbolStatus(exists=self.exists, is_open=self.is_open)

    async def get_proposal(self, sym, ctype, amount):
        amt = Decimal(str(amount))
        gross = (amt * (Decimal("1") + self.payout)).quantize(Decimal("0.01"))
        return Proposal(id="pid", ask_price=amt, payout=gross, spot=Decimal("1.0"))

    async def buy_and_settle(self, proposal, *, timeout_s=None):
        res = self.results[self._i] if self._i < len(self.results) else "lost"
        self._i += 1
        self.bought.append(proposal.ask_price)
        profit = (proposal.payout - proposal.ask_price)
        if res == "won":
            self.balance += profit
        else:
            self.balance -= proposal.ask_price
        return Settlement(
            contract_id=f"cid{self._i}", result=res,
            entry_spot=Decimal("1.0"), exit_spot=Decimal("1.1"),
            profit=(profit if res == "won" else -proposal.ask_price),
            buy_price=proposal.ask_price,
        )


@pytest.fixture
def capture(monkeypatch, tmp_path):
    """Captura los avisos de Telegram y redirige los CSV a un tmp."""
    sent: list[str] = []

    async def fake_notify(text):
        sent.append(text)

    monkeypatch.setattr(main, "notify", fake_notify)
    monkeypatch.setattr(config, "LEVELS_CSV", tmp_path / "levels.csv")
    monkeypatch.setattr(config, "CYCLES_CSV", tmp_path / "cycles.csv")
    monkeypatch.setattr(config, "ERRORS_LOG", tmp_path / "errors.log")
    return sent


def _past_schedule() -> scheduler.Schedule:
    """Horas de ejecucion en el pasado -> sleep_until retorna ya; no espera nada real."""
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    return scheduler.Schedule(
        skipped=False, reason="", run_times_utc=[past, past, past],
        entry_local_signal=past, entry_local_display=past, gale_mismatch=False,
    )


def _sig(par="EUR/USD", direction="CALL"):
    return Signal(par=par, entry_hhmm="00:45", direction=direction)


def _joined(sent):
    return "\n".join(sent)


# --------------------------------------------------------------------------
#  Mercado no encontrado / cerrado (lo que pidio Esteban)
# --------------------------------------------------------------------------
async def test_mercado_no_encontrado_al_recibir(capture):
    fake = FakeBroker(exists=False)
    # Schedule fijo (no depende de la hora real) para llegar al chequeo de mercado.
    real_build = main.scheduler.build_schedule
    main.scheduler.build_schedule = lambda signal, now_utc=None: _past_schedule()
    try:
        await main.handle_message("USD/TRY;00:45;PUT 🟥", fake)
    finally:
        main.scheduler.build_schedule = real_build
    assert any("Mercado No Encontrado / No Disponible" in m for m in capture)
    assert fake.bought == []  # NO se opero nada


async def test_mercado_cerrado_no_opera_nivel(capture):
    fake = FakeBroker(is_open=False, results=["won"])
    await main.run_cycle(fake, _sig(), _past_schedule())
    assert any("Mercado cerrado" in m for m in capture)
    assert fake.bought == []  # nunca compro


# --------------------------------------------------------------------------
#  Ruido: ni aviso ni operacion
# --------------------------------------------------------------------------
async def test_ruido_no_acciona(capture):
    fake = FakeBroker()
    await main.handle_message("🔥 8 WINS / 0 LOSS HOY 🔥", fake)
    assert capture == []
    assert fake.bought == []


# --------------------------------------------------------------------------
#  Resultados de trading (Gale ceil por defecto: 1.00 / 2.12 / 4.47)
# --------------------------------------------------------------------------
async def test_win_en_entrada(capture):
    fake = FakeBroker(results=["won"])
    await main.run_cycle(fake, _sig(), _past_schedule())
    assert fake.bought == [Decimal("1.00")]
    assert any("GANO" in m for m in capture)
    assert any("WIN en Entrada" in m for m in capture)


async def test_win_en_gale1(capture):
    fake = FakeBroker(results=["lost", "won"])
    await main.run_cycle(fake, _sig(), _past_schedule())
    assert fake.bought == [Decimal("1.00"), Decimal("2.12")]
    assert any("WIN en Gale 1" in m for m in capture)


async def test_perdida_total(capture):
    fake = FakeBroker(results=["lost", "lost", "lost"])
    await main.run_cycle(fake, _sig(), _past_schedule())
    assert fake.bought == [Decimal("1.00"), Decimal("2.12"), Decimal("4.47")]
    # Neto del ciclo perdido = -(1.00 + 2.12 + 4.47) = -7.59 (modo ceil)
    assert any("LOSS" in m and "-7.59" in m.replace("$", "") for m in capture)


async def test_flujo_completo_desde_mensaje(capture):
    """handle_message con senal valida + mercado abierto -> programa y opera (win)."""
    import asyncio

    fake = FakeBroker(results=["won"])
    # schedule con entrada inmediata: parcheamos build_schedule para no esperar.
    import scheduler as sch

    real_build = sch.build_schedule
    main.scheduler.build_schedule = lambda signal, now_utc=None: _past_schedule()
    try:
        await main.handle_message("EUR/USD;00:45;CALL 🟩", fake)
        # handle_message lanza run_cycle como task; esperar a que termine.
        pendientes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pendientes:
            await asyncio.gather(*pendientes)
    finally:
        main.scheduler.build_schedule = real_build

    assert any("programada" in m for m in capture)
    assert fake.bought == [Decimal("1.00")]
    assert any("GANO" in m for m in capture)
