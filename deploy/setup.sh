#!/usr/bin/env bash
#
# setup.sh — instala el bot en un VPS Ubuntu 24.04 LTS (clouding.io u otro).
# Correr DENTRO de la carpeta del proyecto, en el VPS, tras subir los archivos.
#   bash deploy/setup.sh
#
# Hace: deps del sistema, venv de Python, instala requirements, crea logs/,
# configura logrotate y deja listo (pero NO arranca) el servicio systemd.
#
set -euo pipefail

# Raiz del proyecto = carpeta padre de este script.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
USER_NAME="$(whoami)"

# Si ya somos root, $SUDO sobra (y puede no estar instalado). Si no, usamos sudo.
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Proyecto: $HERE  (usuario: $USER_NAME)"

echo "==> 1/5 Paquetes del sistema"
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip git tzdata

echo "==> 2/5 Entorno virtual + dependencias"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "==> 3/5 Carpeta de logs"
mkdir -p logs

echo "==> 4/5 logrotate (rota SOLO *.log, deja intactos los CSV de datos)"
$SUDO tee /etc/logrotate.d/tradingbot >/dev/null <<EOF
$HERE/logs/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
EOF

echo "==> 5/5 Servicio systemd (auto-restart + arranca al reiniciar el VPS)"
$SUDO tee /etc/systemd/system/tradingbot.service >/dev/null <<EOF
[Unit]
Description=Telegram -> IQ Option copy trading bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$HERE
ExecStart=$HERE/.venv/bin/python -u main.py
Restart=always
RestartSec=10
StandardOutput=append:$HERE/logs/run.log
StandardError=append:$HERE/logs/run.log

[Install]
WantedBy=multi-user.target
EOF

$SUDO systemctl daemon-reload

echo ""
echo "============================================================"
echo "Setup OK."
echo "ANTES de arrancar, asegura que existan en $HERE :"
echo "  - .env  (credenciales)"
echo "  - telegram_signal_listener.session  (sesion telethon)"
echo ""
echo "Arrancar el bot:"
echo "  $SUDO systemctl enable --now tradingbot"
echo "Ver estado / logs:"
echo "  systemctl status tradingbot"
echo "  tail -f $HERE/logs/run.log"
echo "Parar:"
echo "  $SUDO systemctl stop tradingbot"
echo "============================================================"
