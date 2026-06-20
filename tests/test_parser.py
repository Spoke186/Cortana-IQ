"""Tests del parser (§1, §13.2): senal valida, resumen a ignorar, edge cases."""
from parser import parse_signal

SENAL_PUT = (
    "🔔 SEÑAL\n"
    "USD/TRY;00:45;PUT 🟥\n"
    "🕐 TIEMPO HASTA 00:50\n"
    "1er GALE —> TIEMPO HASTA 00:55\n"
    "2º GALE —> TIEMPO HASTA 01:00\n"
)

SENAL_CALL = "EUR/JPY;14:30;CALL 🟩"

RESUMEN = (
    "📊 RESULTADOS DEL DÍA\n"
    "EUR/USD ->WIN\n"
    "GBP/JPY ->WIN\n"
    "8 WINS / 0 LOSS 🔥🔥\n"
    "Pinned Message\n"
)


def test_senal_put_valida():
    s = parse_signal(SENAL_PUT)
    assert s is not None
    assert s.par == "USD/TRY"
    assert s.entry_hhmm == "00:45"
    assert s.direction == "PUT"
    assert s.iq_contract_type == "PUT"


def test_declared_gale_times_extraidos():
    s = parse_signal(SENAL_PUT)
    assert s is not None
    assert s.declared_gale_hhmm == ["00:50", "00:55", "01:00"]


def test_senal_call_valida():
    s = parse_signal(SENAL_CALL)
    assert s is not None
    assert s.par == "EUR/JPY"
    assert s.entry_hhmm == "14:30"
    assert s.direction == "CALL"


def test_resumen_se_ignora():
    assert parse_signal(RESUMEN) is None


def test_vacio_o_none():
    assert parse_signal("") is None
    assert parse_signal(None) is None  # type: ignore[arg-type]


def test_par_sin_slash_no_matchea():
    assert parse_signal("USDTRY;00:45;PUT") is None


def test_direccion_invalida_no_matchea():
    assert parse_signal("USD/TRY;00:45;BUY") is None


def test_hora_malformada_no_matchea():
    assert parse_signal("USD/TRY;0:45;PUT") is None  # falta el cero de la hora


def test_senal_embebida_en_texto():
    txt = "Atencion equipo!\n\n  NZD/USD;09:05;CALL 🟩  \n\nbuena suerte"
    s = parse_signal(txt)
    assert s is not None
    assert s.par == "NZD/USD"
    assert s.direction == "CALL"
