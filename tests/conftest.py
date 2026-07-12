"""
conftest.py — fija variables de entorno DUMMY antes de importar config en los tests.

Asi parser/scheduler/gale se pueden testear sin .env real y sin tocar IQ Option/Telegram.
(Se setean en tiempo de import de conftest, antes de la coleccion de tests.)
"""
import os

_DUMMY = {
    "TG_API_ID": "1",
    "TG_API_HASH": "dummy",
    "TG_CHANNEL": "-1000000000001",       # numerico: el registro multicanal necesita int
    "TG_CH_CONSISTENTES": "-1000000000002",
    "TG_CH_GOLD": "-1000000000003",
    "IQ_EMAIL": "dummy@example.com",
    "IQ_PASSWORD": "dummy",
    "IQ_ACCOUNT_TYPE": "practice",
    "NOTIFY_BOT_TOKEN": "dummy",
    "NOTIFY_CHAT_ID": "1",
    "SIGNAL_TIMEZONE": "America/Sao_Paulo",
    "DISPLAY_TIMEZONE": "America/Bogota",
    "GALE_ROUNDING": "ceil",
    "STOP_LOSS_BALANCE": "None",
}
for _k, _v in _DUMMY.items():
    os.environ.setdefault(_k, _v)

import sys
from pathlib import Path

# Permite importar los modulos del proyecto (config, parser, ...) desde tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
