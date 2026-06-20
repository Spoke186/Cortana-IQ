"""
notifier.py — bot PROPIO de avisos (NO el canal del senalero). (§8)

- UTF-8 explicito: requests serializa el JSON como UTF-8 (acentos: Direccion, Operacion, Sesion).
- NUNCA un catch vacio: todo fallo de envio se loguea a errors.log.
- Envio sincrono y simple; el orquestador lo llama desde un executor para no bloquear el loop.
"""
from __future__ import annotations

import json
import time

import requests

import config
import logger

_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 15  # segundos
_RETRIES = 3   # red inestable (ConnectionReset 10054): reintentar antes de rendirse
_BACKOFF = 2.0  # segundos entre reintentos


def _send_once(url: str, payload: dict) -> tuple[bool, str | None]:
    """Un intento. Devuelve (ok, motivo_de_fallo). ok=True -> enviado; motivo None."""
    try:
        # data= con UTF-8 explicito; Telegram acepta application/x-www-form-urlencoded.
        resp = requests.post(
            url,
            data={k: (json.dumps(v) if isinstance(v, bool) else v) for k, v in payload.items()},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"{exc!r}"

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:300]}"

    try:
        ok = resp.json().get("ok", False)
    except ValueError as exc:
        return False, f"respuesta no-JSON: {exc!r}"

    if not ok:
        return False, f"telegram ok=false: {resp.text[:300]}"

    return True, None


def send(text: str, *, parse_mode: str | None = None) -> bool:
    """
    Envia 'text' al chat de Esteban. Devuelve True si Telegram confirmo ok.
    Reintenta ante fallos transitorios de red. Cualquier fallo final se loguea; nunca se traga.
    """
    url = _API.format(token=config.NOTIFY_BOT_TOKEN)
    payload: dict = {
        "chat_id": config.NOTIFY_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    last_reason: str | None = None
    for attempt in range(1, _RETRIES + 1):
        ok, reason = _send_once(url, payload)
        if ok:
            return True
        last_reason = reason
        if attempt < _RETRIES:
            time.sleep(_BACKOFF)

    logger.log_error("notifier.send", f"fallo tras {_RETRIES} intentos: {last_reason}")
    return False
