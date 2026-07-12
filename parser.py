"""
parser.py — extrae la senal de entrada del texto crudo de Telegram (§1).

Regla dura (§1.2): si el mensaje NO contiene una linea que matchee EXACTAMENTE el regex
de senal de entrada, se ignora (es resumen/reporte/motivacional/pinned).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Linea clave de §1.1:  USD/TRY;00:45;PUT 🟥
#
# Robustez para canales ruidosos (el grupo manda muchos mensajes, no solo senales):
#   - \s* alrededor de ';' tolera "USD/TRY ; 00:45 ; PUT" o pegado.
#   - (?i:PUT|CALL) acepta put/Call/CALL y se normaliza a mayusculas.
#   - El par sigue siendo ESTRICTO mayusculas ISO/ISO para no pescar texto al azar.
# Esta especificidad es la que hace que el bot "sepa cual es la senal": cualquier mensaje que
# NO contenga exactamente PAR/PAR;HH:MM;DIR se ignora (resumenes, motivacionales, pinned, etc.).
SIGNAL_RE = re.compile(
    r"(?P<par>[A-Z]{3}/[A-Z]{3})"          # par ISO/ISO (USD/TRY, EUR/JPY, XAU/USD...)
    r"\s*;\s*"
    r"(?P<hora>\d{2}:\d{2})"               # hora de entrada HH:MM (TZ de la senal = UTC-3)
    r"\s*;\s*"
    r"(?P<dir>(?i:PUT|CALL))"              # direccion (case-insensitive, se normaliza)
    # CRITICO: NO accionar los RESUMENES de resultados del canal. El senalero postea recaps
    # con formato identico al de una entrada pero seguido de '->WIN/->LOSS':
    #   "USD/ZAR; 00:35; PUT->WIN ✅\nUSD/ZAR; 00:45; PUT->LOSS ❌\n7 WINS / 3 LOSS"
    # Sin este lookahead, SIGNAL_RE.search() pesca el PRIMER 'PAR;HH:MM;DIR' del recap y el bot
    # opera un par que el canal NUNCA mando como entrada (bug real: USD/ZAR operado desde recaps).
    # Una entrada real termina en emoji/fin de linea, jamas en flecha de resultado.
    r"(?!\s*(?:-+>|—+>|→))"                # rechaza '->', '-->', '—>', '→' (linea de resultado)
)

# Lineas de Gale declaradas por el canal: "TIEMPO HASTA 00:50", "1er GALE —> TIEMPO HASTA 00:55"
GALE_TIME_RE = re.compile(r"TIEMPO\s+HASTA\s+(?P<hora>\d{2}:\d{2})", re.IGNORECASE)


@dataclass(frozen=True)
class Signal:
    """Senal de entrada parseada. La hora esta en la TZ del PROVEEDOR (ver source), aun sin convertir."""
    par: str            # "USD/TRY"
    entry_hhmm: str     # "00:45"
    direction: str      # "PUT" | "CALL"
    raw: str = ""       # texto original (para logging/depuracion)
    # Horas de Gale que el canal declaro (HH:MM), para cruzar contra las derivadas (§1.4).
    declared_gale_hhmm: list[str] = field(default_factory=list)
    # Multicanal (2026-07-11): expiracion del contrato (min) y proveedor que la emitio.
    duration_min: int = 5           # 1 (M1) | 5 (M5). Define tambien el paso de Gale.
    source: str = "main"            # key del proveedor (providers.py)
    # Fecha CALENDARIO de la entrada (ISO 'YYYY-MM-DD' en la TZ del proveedor) para las listas
    # diarias con fecha en el header. None = canal en vivo 'main' (el scheduler infiere hoy/manana).
    # Con fecha, el scheduler agenda en esa fecha EXACTA y salta si ya paso (no rueda al futuro).
    entry_date: str | None = None

    @property
    def iq_contract_type(self) -> str:
        """PUT -> Fall/Bajar, CALL -> Rise/Subir. IQ turbo usa 'put'/'call' (§3)."""
        return self.direction


def parse_signal(text: str) -> Signal | None:
    """
    Devuelve un Signal si el texto contiene una senal de entrada valida; None si no.

    None significa: IGNORAR el mensaje (no es una orden de operar). Esto cubre todos los
    reportes/resumenes de §1.2 sin necesidad de listarlos: si no matchea, no se acciona.
    """
    if not text:
        return None

    m = SIGNAL_RE.search(text)
    if not m:
        return None

    # Validar rango horario: el regex acepta "99:99"; un HH:MM imposible NO es senal -> ignorar.
    hh, mm = (int(x) for x in m.group("hora").split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None

    # Horas de Gale declaradas (todas las "TIEMPO HASTA HH:MM"). La primera suele ser
    # el cierre de la entrada (entrada+5), no un Gale; el cruce real lo hace el scheduler.
    declared = [g.group("hora") for g in GALE_TIME_RE.finditer(text)]

    return Signal(
        par=m.group("par").upper(),
        entry_hhmm=f"{hh:02d}:{mm:02d}",
        direction=m.group("dir").upper(),
        raw=text.strip(),
        declared_gale_hhmm=declared,
    )
