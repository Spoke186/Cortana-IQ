# Deploy del bot en un VPS (clouding.io, Ubuntu 24.04)

Mover el bot a un VPS para que corra 24/7 sin tu PC. Pasos copy-paste.

> **Regla de oro:** una sola copia del bot a la vez. Cuando el VPS quede andando,
> **para el bot de tu PC.** Telethon usa la misma `.session`; si corre desde 2 IPs
> a la vez, Telegram puede **revocar la sesión**.

---

## 0. Comprar el VPS
- clouding.io → crear servidor.
- **Ubuntu 24.04 LTS**, 1 vCore, 2 GB RAM, **10 GB SSD**.
- Añadir tu **clave SSH** (o usar contraseña). Anota la **IP** del servidor.

---

## 1. Entrar por SSH (desde tu PC, PowerShell)
```powershell
ssh root@LA_IP_DEL_VPS
```
(Recomendado: crear un usuario normal en vez de root)
```bash
adduser esteban
usermod -aG sudo esteban
su - esteban
```

---

## 2. Subir los archivos (desde tu PC, PowerShell — NO dentro del SSH)
Desde `C:\Users\Esteb\Downloads\Cortana`:
```powershell
scp -r telegram-deriv-bot esteban@LA_IP_DEL_VPS:~/
```
Esto sube TODO, incluidos los archivos que NO van a git pero SÍ se necesitan:
- `.env` (credenciales)
- `telegram_signal_listener.session` (sesión telethon — evita re-login)

> Si `scp` no copia los ocultos, súbelos sueltos:
> ```powershell
> scp telegram-deriv-bot\.env esteban@LA_IP:~/telegram-deriv-bot/
> scp telegram-deriv-bot\telegram_signal_listener.session esteban@LA_IP:~/telegram-deriv-bot/
> ```

---

## 3. Instalar (dentro del SSH, en el VPS)
```bash
cd ~/telegram-deriv-bot
bash deploy/setup.sh
```
El script instala Python, dependencias, logrotate y deja el servicio systemd listo.

> Si da error tipo `bad interpreter: ^M` (saltos de línea de Windows):
> ```bash
> sudo apt-get install -y dos2unix && dos2unix deploy/setup.sh && bash deploy/setup.sh
> ```

---

## 4. Confirmar credenciales y cuenta
```bash
nano ~/telegram-deriv-bot/.env
```
- Verifica `IQ_ACCOUNT_TYPE` (`practice` para pruebas, `real` para dinero real).
- Que estén todas las claves (TG_*, IQ_*, NOTIFY_*).

---

## 5. Arrancar
```bash
sudo systemctl enable --now tradingbot
systemctl status tradingbot          # debe decir active (running)
tail -f ~/telegram-deriv-bot/logs/run.log
```
En el log debe aparecer: `Telethon conectado`, `Backlog sembrado`, `Escuchando canal`.
El bot de avisos te manda "🟢 Bot iniciado" por Telegram.

> **IQ puede pedir confirmación por email** la primera vez (IP nueva, datacenter).
> Confirma el correo de IQ Option y reinicia: `sudo systemctl restart tradingbot`.

---

## 6. Apagar el bot de tu PC
Una vez el VPS confirme "Bot iniciado", **para el de tu PC** (una sola sesión).
Ya puedes apagar tu computador; el VPS sigue solo.

---

## Comandos útiles (en el VPS)
| Acción | Comando |
|---|---|
| Estado | `systemctl status tradingbot` |
| Ver logs en vivo | `tail -f ~/telegram-deriv-bot/logs/run.log` |
| Parar | `sudo systemctl stop tradingbot` |
| Arrancar | `sudo systemctl start tradingbot` |
| Reiniciar | `sudo systemctl restart tradingbot` |
| Desactivar arranque al boot | `sudo systemctl disable tradingbot` |
| Bajar CSV de resultados a tu PC | `scp esteban@LA_IP:~/telegram-deriv-bot/logs/*.csv .` |

Reinicia el bot solo (`Restart=always`) si crashea, y arranca automático si el VPS se reinicia.
