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
import providers
import scheduler
from iqoption_client import Proposal, Settlement, SymbolStatus
from parser import Signal

# Proveedor 'main' del registro (canal en vivo, 5min, 2 gale, buckets por par).
MAIN_PROV = next(p for cid, p in providers.REGISTRY.items() if p.key == "main")
MAIN_CID = MAIN_PROV.channel_id
CONS_PROV = next(p for cid, p in providers.REGISTRY.items() if p.key == "consistentes")


# --------------------------------------------------------------------------
#  Broker FALSO
# --------------------------------------------------------------------------
class FakeBroker:
    def __init__(self, *, exists=True, is_open=True, payout="0.90", results=None, balance="100", trend=None):
        self.exists = exists
        self.is_open = is_open
        self.payout = Decimal(payout)          # fraccion de ganancia
        self.results = list(results or [])     # "won"/"lost" por nivel
        self.balance = Decimal(balance)
        self.trend = trend                     # 'CALL'|'PUT'|None que devuelve get_trend
        self.bought: list[Decimal] = []         # stake comprado por nivel (solo finales)
        self._i = 0

    async def connect(self): ...
    async def disconnect(self): ...
    async def reconnect(self): ...

    async def get_trend(self, iq_symbol, interval, fast, slow):
        return self.trend

    async def get_balance(self):
        return self.balance

    async def get_atr(self, sym, n=14, interval=300):
        return float("nan")     # el ATR es solo dato; no afecta la mecanica del ciclo

    async def check_symbol(self, sym):
        return SymbolStatus(exists=self.exists, is_open=self.is_open)

    async def get_proposal(self, sym, ctype, amount, duration_min=5):
        amt = Decimal(str(amount))
        gross = (amt * (Decimal("1") + self.payout)).quantize(Decimal("0.01"))
        return Proposal(id="pid", ask_price=amt, payout=gross, spot=Decimal("1.0"), duration_min=duration_min)

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
    monkeypatch.setattr(config, "DEMO_CSV", tmp_path / "demo_entries.csv")
    # Tests de MECANICA del ciclo: fijar todos los buckets a $1 para aislar de la politica de stake.
    monkeypatch.setattr(config, "STAKE_REAL", Decimal("1.00"))
    monkeypatch.setattr(config, "STAKE_OTC", Decimal("1.00"))
    monkeypatch.setattr(config, "STAKE_ALTO", Decimal("1.00"))
    # Estado de dedup/anti-doble-trade es global del modulo: arrancar limpio cada test.
    main._seen_text.clear()
    main._scheduled_cycles.clear()
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


def _fixed_past_schedule() -> scheduler.Schedule:
    """Schedule en el pasado con hora FIJA (no now()): mismo cycle_id en llamadas repetidas."""
    t = datetime(2020, 1, 1, 0, 45, tzinfo=timezone.utc)
    return scheduler.Schedule(
        skipped=False, reason="", run_times_utc=[t, t, t],
        entry_local_signal=t, entry_local_display=t, gale_mismatch=False,
    )


async def _drain_tasks() -> None:
    """Espera a que terminen las tasks de run_cycle lanzadas por handle_message."""
    import asyncio
    pend = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pend:
        await asyncio.gather(*pend)


def _joined(sent):
    return "\n".join(sent)


# --------------------------------------------------------------------------
#  Mercado no encontrado / cerrado (lo que pidio Esteban)
# --------------------------------------------------------------------------
async def test_mercado_no_encontrado_al_recibir(capture):
    fake = FakeBroker(exists=False)
    # Schedule fijo (no depende de la hora real) para llegar al chequeo de mercado.
    real_build = main.scheduler.build_schedule
    main.scheduler.build_schedule = lambda signal, now_utc=None, **kw: _past_schedule()
    try:
        await main.handle_message("USD/TRY;00:45;PUT 🟥", MAIN_CID, fake)
    finally:
        main.scheduler.build_schedule = real_build
    assert any("Mercado No Encontrado / No Disponible" in m for m in capture)
    assert fake.bought == []  # NO se opero nada


async def test_mercado_cerrado_no_opera_nivel(capture):
    fake = FakeBroker(is_open=False, results=["won"])
    await main.run_cycle(fake, _sig(), _past_schedule(), MAIN_PROV)
    assert any("Mercado cerrado" in m for m in capture)
    assert fake.bought == []  # nunca compro


# --------------------------------------------------------------------------
#  Ruido: ni aviso ni operacion
# --------------------------------------------------------------------------
async def test_ruido_no_acciona(capture):
    fake = FakeBroker()
    await main.handle_message("🔥 8 WINS / 0 LOSS HOY 🔥", MAIN_CID, fake)
    assert capture == []
    assert fake.bought == []


# --------------------------------------------------------------------------
#  Resultados de trading (Gale ceil por defecto: 1.00 / 2.12 / 4.47)
# --------------------------------------------------------------------------
async def test_win_en_entrada(capture):
    fake = FakeBroker(results=["won"])
    await main.run_cycle(fake, _sig(), _past_schedule(), MAIN_PROV)
    assert fake.bought == [Decimal("1.00")]
    assert any("GANO" in m for m in capture)
    assert any("WIN en Entrada" in m for m in capture)


async def test_win_en_gale1(capture):
    fake = FakeBroker(results=["lost", "won"])
    await main.run_cycle(fake, _sig(), _past_schedule(), MAIN_PROV)
    assert fake.bought == [Decimal("1.00"), Decimal("2.12")]
    assert any("WIN en Gale 1" in m for m in capture)


async def test_perdida_total(capture):
    # MAX_GALE_LEVELS=2: perdida total = entrada + Gale 1 + Gale 2.
    fake = FakeBroker(results=["lost", "lost", "lost"])
    await main.run_cycle(fake, _sig(), _past_schedule(), MAIN_PROV)
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
    main.scheduler.build_schedule = lambda signal, now_utc=None, **kw: _past_schedule()
    try:
        await main.handle_message("EUR/USD;00:45;CALL 🟩", MAIN_CID, fake)
        # handle_message lanza run_cycle como task; esperar a que termine.
        pendientes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if pendientes:
            await asyncio.gather(*pendientes)
    finally:
        main.scheduler.build_schedule = real_build

    assert any("programada" in m for m in capture)
    assert fake.bought == [Decimal("1.00")]
    assert any("GANO" in m for m in capture)


# --------------------------------------------------------------------------
#  Ediciones del canal (el canal EDITA sus posts tras publicarlos)
# --------------------------------------------------------------------------
async def test_edicion_mete_par_se_opera(capture, monkeypatch):
    """POST sin par (placeholder) + EDICION que mete el par -> al reprocesar la edicion, opera."""
    fake = FakeBroker(results=["won"])
    monkeypatch.setattr(main.scheduler, "build_schedule", lambda signal, now_utc=None, **kw: _fixed_past_schedule())

    # 1) version POST: sin linea de senal -> parse None -> ignorada (ni aviso ni operacion).
    await main.process_message("💰 Vencimiento en 5 minutos", 555, MAIN_CID, fake)
    assert capture == []
    assert fake.bought == []

    # 2) version EDITADA (mismo id) ya trae el par -> texto cambio -> se reprocesa y opera.
    await main.process_message("EUR/GBP;10:40;PUT 🟥", 555, MAIN_CID, fake)
    await _drain_tasks()
    assert any("programada" in m for m in capture)
    assert fake.bought == [Decimal("1.00")]
    assert any("GANO" in m for m in capture)


async def test_edicion_no_duplica_trade(capture, monkeypatch):
    """La MISMA entrada que vuelve (edicion cosmetica o por 2 vias) NO se opera dos veces."""
    fake = FakeBroker(results=["won", "won"])
    monkeypatch.setattr(main.scheduler, "build_schedule", lambda signal, now_utc=None, **kw: _fixed_past_schedule())

    # 1) senal valida -> opera una vez.
    await main.process_message("EUR/GBP;10:40;PUT 🟥", 777, MAIN_CID, fake)
    await _drain_tasks()
    assert fake.bought == [Decimal("1.00")]

    # 2) edicion cosmetica (mismo id, texto distinto, MISMA senal) -> reprocesa pero el guard
    #    por cycle_id evita re-operar.
    await main.process_message("EUR/GBP;10:40;PUT 🟥 (editado)", 777, MAIN_CID, fake)
    await _drain_tasks()
    assert fake.bought == [Decimal("1.00")]  # sigue siendo UNA sola operacion


# --------------------------------------------------------------------------
#  Stake por mercado + filtro de tendencia (multicanal 2026-07-11)
# --------------------------------------------------------------------------
async def test_mercado_deshabilitado_stake0_no_opera(capture):
    """Par con stake 0 en STAKE_TABLE (perdedor) -> no se programa ni opera; solo loguea."""
    fake = FakeBroker(results=["won"])
    # main: USD/CHF esta en la tabla a 0.00 (perdedor).
    sig = Signal(par="USD/CHF", entry_hhmm="00:45", direction="PUT")
    await main._schedule_one(sig, MAIN_PROV, fake)
    assert fake.bought == []
    assert not any("programada" in m for m in capture)


async def test_trend_contra_no_opera(capture):
    """Proveedor con filtro de tendencia: senal CONTRA el trend -> no se opera el ciclo."""
    fake = FakeBroker(results=["won"], trend="CALL")     # mercado alcista
    sig = Signal(par="EUR/GBP", entry_hhmm="00:45", direction="PUT",  # PUT va contra CALL
                 duration_min=1, source="consistentes")
    await main.run_cycle(fake, sig, _past_schedule(), CONS_PROV)
    assert fake.bought == []
    assert any("CONTRA tendencia" in m for m in capture)


async def test_trend_a_favor_opera(capture):
    """Filtro de tendencia: senal A FAVOR del trend -> opera normal (stake por mercado)."""
    fake = FakeBroker(results=["won"], trend="PUT")      # mercado bajista, senal PUT: a favor
    sig = Signal(par="EUR/GBP", entry_hhmm="00:45", direction="PUT",
                 duration_min=1, source="consistentes")
    await main.run_cycle(fake, sig, _past_schedule(), CONS_PROV)
    assert fake.bought == [config.STAKE_TABLE["consistentes"]["EUR/GBP"]]  # stake por mercado
    assert any("GANO" in m for m in capture)


async def test_trend_none_no_bloquea(capture):
    """Si no se puede medir el trend (None) -> se opera igual (no bloquear por falta de datos)."""
    fake = FakeBroker(results=["won"], trend=None)
    sig = Signal(par="EUR/GBP", entry_hhmm="00:45", direction="PUT",
                 duration_min=1, source="consistentes")
    await main.run_cycle(fake, sig, _past_schedule(), CONS_PROV)
    assert fake.bought == [config.STAKE_TABLE["consistentes"]["EUR/GBP"]]


async def test_mismo_texto_no_reprocesa(capture, monkeypatch):
    """Mismo id + mismo texto (vivo + polling) -> no se reprocesa (dedup id+texto)."""
    fake = FakeBroker(results=["won", "won"])
    monkeypatch.setattr(main.scheduler, "build_schedule", lambda signal, now_utc=None, **kw: _fixed_past_schedule())

    await main.process_message("EUR/GBP;10:40;PUT 🟥", 888, MAIN_CID, fake)
    await _drain_tasks()
    await main.process_message("EUR/GBP;10:40;PUT 🟥", 888, MAIN_CID, fake)  # identico -> ignorado
    await _drain_tasks()
    assert fake.bought == [Decimal("1.00")]
