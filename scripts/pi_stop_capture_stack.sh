#!/usr/bin/env bash
set -euo pipefail

repo_dir="${SPECTRUM_REPO_DIR:-$HOME/spectrum}"
cd "$repo_dir"

kill_listener() {
  port="$1"
  pid="$(ss -ltnp 2>/dev/null | sed -n "s/.*:$port .*pid=\\([0-9]*\\).*/\\1/p" | head -n1)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
  fi
}

for pidfile in logs/webui.pid logs/webui-dev.pid logs/acquisition.pid; do
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
    fi
    rm -f "$pidfile"
  fi
done

kill_listener "${SPECTRUM_WEBUI_PORT:-3005}"
kill_listener "${ACQUISITION_API_PORT:-8000}"

echo "capture stack stopped"
