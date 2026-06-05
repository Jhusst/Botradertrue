#!/usr/bin/env bash
# Instala servicios systemd de usuario para arrancar el bot al encender la PC.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_SYSTEMD="${HOME}/.config/systemd/user"
mkdir -p "${USER_SYSTEMD}"

for unit in trading-bot-ollama trading-bot-api; do
  sed "s|@PROJECT_ROOT@|${ROOT}|g" \
    "${ROOT}/deploy/systemd/${unit}.service" \
    > "${USER_SYSTEMD}/${unit}.service"
  echo "Instalado: ${USER_SYSTEMD}/${unit}.service"
done

systemctl --user daemon-reload
systemctl --user enable trading-bot-ollama.service trading-bot-api.service
systemctl --user restart trading-bot-ollama.service trading-bot-api.service

if command -v loginctl >/dev/null 2>&1; then
  loginctl enable-linger "${USER}" 2>/dev/null || true
  echo "Linger activado: el bot puede arrancar sin iniciar sesión gráfica."
fi

echo ""
echo "Estado:"
systemctl --user --no-pager status trading-bot-ollama.service trading-bot-api.service || true
echo ""
"${ROOT}/scripts/check_binance_ip.sh" || true
echo ""
echo "Comandos útiles:"
echo "  systemctl --user status trading-bot-api"
echo "  systemctl --user restart trading-bot-api"
echo "  systemctl --user stop trading-bot-ollama trading-bot-api"
echo "  journalctl --user -u trading-bot-api -f"
