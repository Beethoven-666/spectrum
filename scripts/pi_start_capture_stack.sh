#!/usr/bin/env bash
set -euo pipefail

repo_dir="${SPECTRUM_REPO_DIR:-$HOME/spectrum}"
api_port="${ACQUISITION_API_PORT:-8000}"
web_port="${SPECTRUM_WEBUI_PORT:-3005}"

export PATH="$HOME/.local/bin:$PATH"

cd "$repo_dir"
mkdir -p logs

systemctl --user stop patrol-camera-push.service 2>/dev/null || true

listener_pid() {
  ss -ltnp 2>/dev/null | sed -n "s/.*:$1 .*pid=\\([0-9]*\\).*/\\1/p" | head -n1
}

# True if something is already listening on the given TCP port. Match the
# Local Address:Port column precisely: the port must be preceded by ':' and
# followed by whitespace, anchored to that column, so e.g. port 800 cannot
# false-match a listener on 8000 (or an address that merely contains "800").
port_in_use() {
  ss -ltn 2>/dev/null | awk -v p=":$1\$" '$4 ~ p {found=1} END {exit found ? 0 : 1}'
}

if port_in_use "$api_port"; then
  listener_pid "$api_port" > logs/acquisition.pid
else
  nohup acquisition/.venv/bin/spectrum-acq \
    --data-dir ./data \
    --hardware \
    --host 127.0.0.1 \
    --port "$api_port" \
    > logs/acquisition.log 2>&1 < /dev/null &
  echo "$!" > logs/acquisition.pid
fi

if port_in_use "$web_port"; then
  listener_pid "$web_port" > logs/webui.pid
else
  ACQUISITION_API_BASE_URL="http://127.0.0.1:$api_port" \
    nohup npm run start -w h1-webui -- --hostname 0.0.0.0 --port "$web_port" \
    > logs/webui.log 2>&1 < /dev/null &
  echo "$!" > logs/webui.pid
fi

echo "acquisition: http://127.0.0.1:$api_port"
echo "webui: http://croprix-spectrum.local:$web_port/acquisition"
