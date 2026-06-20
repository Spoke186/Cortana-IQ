"""
test_parser_noise.py — confirma que el bot SABE cual es la senal en un canal ruidoso.

El grupo manda muchos mensajes (resultados, motivacionales, analisis, pinned, anuncios).
El bot SOLO debe accionar el formato PAR/PAR;HH:MM;PUT|CALL y ENTONCES ignorar todo lo demas.
"""
import pytest

from parser import parse_signal

# --------------------------------------------------------------------------
#  RUIDO: nada de esto debe accionar (parse_signal -> None)
# --------------------------------------------------------------------------
NOISE = [
    "📊 RESULTADO: EUR/USD ->WIN ✅",
    "GBP/JPY ->LOSS ❌",
    "🔥🔥 8 WINS / 0 LOSS HOY 🔥🔥",
    "Buenos dias traders! Hoy vamos con todo 💪",
    "⚠️ Proxima senal en 5 minutos, esten atentos",
    "GANAMOS! +$450 en la sesion 🤑",
    "Zona horaria: UTC-3",
    "Pinned Message",
    "📌 Reglas del grupo: respeten el money management",
    "EUR/USD analisis: tendencia alcista en H1",          # par pero sin ;HH:MM;DIR
    "Recuerden hacer GALE si la entrada pierde",
    "PUT en EUR/USD ahora mismo",                          # palabras, no formato
    "00:45 PUT USD/TRY",                                   # orden/separadores incorrectos
    "Entrada a las 00:45 en USD/TRY direccion PUT",        # prosa
    "✅✅✅✅✅✅✅✅",
    "https://t.me/joinchat/xyz",
    "USD/TRY 00:45 PUT",                                   # sin punto y coma
    "USD-TRY;00:45;PUT",                                   # guion en vez de slash
    "US/TRY;00:45;PUT",                                    # par de 2 letras
    "USD/TRY;25:99;PUT",                                   # hora imposible
    "USD/TRY;0:45;PUT",                                    # hora sin cero a la izquierda
    "",
]


@pytest.mark.parametrize("msg", NOISE)
def test_ruido_se_ignora(msg):
    assert parse_signal(msg) is None, f"NO debio accionar: {msg!r}"


# --------------------------------------------------------------------------
#  SENALES VALIDAS: el bot debe capturarlas pese a variaciones de formato
# --------------------------------------------------------------------------
SIGNALS = [
    # (texto, par, hhmm, dir)
    ("USD/TRY;00:45;PUT 🟥", "USD/TRY", "00:45", "PUT"),
    ("EUR/JPY;14:30;CALL 🟩", "EUR/JPY", "14:30", "CALL"),
    ("EUR/JPY ; 14:30 ; CALL", "EUR/JPY", "14:30", "CALL"),          # espacios alrededor de ;
    ("NZD/USD;09:05;call", "NZD/USD", "09:05", "CALL"),              # direccion minuscula
    ("**AUD/CAD;23:58;PUT**", "AUD/CAD", "23:58", "PUT"),            # markdown negrita
    ("XAU/USD;08:00;CALL", "XAU/USD", "08:00", "CALL"),             # oro
    ("Atencion!\n\nGBP/JPY;17:15;PUT 🟥\n\nbuena suerte", "GBP/JPY", "17:15", "PUT"),
    (
        "🔔 SENAL\nUSD/TRY;00:45;PUT 🟥\n🕐 TIEMPO HASTA 00:50\n"
        "1er GALE —> TIEMPO HASTA 00:55\n2º GALE —> TIEMPO HASTA 01:00",
        "USD/TRY", "00:45", "PUT",
    ),
]


@pytest.mark.parametrize("msg,par,hhmm,direction", SIGNALS)
def test_senal_capturada(msg, par, hhmm, direction):
    s = parse_signal(msg)
    assert s is not None, f"DEBIO capturar: {msg!r}"
    assert s.par == par
    assert s.entry_hhmm == hhmm
    assert s.direction == direction
