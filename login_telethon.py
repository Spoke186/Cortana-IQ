"""
login_telethon.py — login de Telethon en 2 pasos SIN input interactivo.

El primer login de Telethon necesita telefono + codigo que Telegram manda. En consolas no
interactivas (como el modo '!' de Claude Code) el input() revienta con EOFError. Este script
pasa todo por ARGUMENTOS, en dos corridas, guardando el estado entre ambas.

USO:
  1) Pedir el codigo (Telegram te lo manda al app / SMS):
       python login_telethon.py request +57XXXXXXXXXX

  2) Confirmar con el codigo recibido:
       python login_telethon.py code 12345

  3) Si tu cuenta tiene verificacion en 2 pasos (contrasena cloud), ademas:
       python login_telethon.py code 12345 --password TU_CLAVE_2FA

Al terminar queda el archivo <TG_SESSION>.session y main.py ya NO pedira nada.
El estado temporal (phone_code_hash) se guarda en .login_state.json (borralo despues).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import config
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

_STATE = Path(__file__).resolve().parent / ".login_state.json"


def _client() -> TelegramClient:
    return TelegramClient(config.TG_SESSION, config.TG_API_ID, config.TG_API_HASH)


async def do_request(phone: str) -> None:
    client = _client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"Ya estabas logueado como: @{getattr(me, 'username', None) or me.id}. Nada que hacer.")
            return
        sent = await client.send_code_request(phone)
        _STATE.write_text(json.dumps({"phone": phone, "hash": sent.phone_code_hash}), encoding="utf-8")
        print(f"Codigo ENVIADO a {phone}. Revisa tu app de Telegram (o SMS).")
        print("Luego corre:  python login_telethon.py code EL_CODIGO")
    finally:
        await client.disconnect()


async def do_code(code: str, password: str | None) -> None:
    if not _STATE.exists():
        print("Falta el paso 1. Corre primero:  python login_telethon.py request +57XXXXXXXXXX")
        return
    st = json.loads(_STATE.read_text(encoding="utf-8"))
    client = _client()
    await client.connect()
    try:
        try:
            await client.sign_in(phone=st["phone"], code=code, phone_code_hash=st["hash"])
        except SessionPasswordNeededError:
            if not password:
                print("Tu cuenta tiene verificacion en 2 pasos. Repite con:")
                print("  python login_telethon.py code EL_CODIGO --password TU_CLAVE_2FA")
                return
            await client.sign_in(password=password)
        me = await client.get_me()
        print(f"LOGIN OK. Sesion guardada como @{getattr(me, 'username', None) or me.id}.")
        print(f"Archivo de sesion: {config.TG_SESSION}.session  ->  ya podes correr  python main.py")
        try:
            _STATE.unlink()  # limpiar estado temporal
        except OSError:
            pass
    finally:
        await client.disconnect()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "request":
        asyncio.run(do_request(args[1]))
    elif len(args) >= 2 and args[0] == "code":
        password = None
        if "--password" in args:
            password = args[args.index("--password") + 1]
        asyncio.run(do_code(args[1], password))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
