#!/usr/bin/env bash
set -euo pipefail

repo_dir="${SPECTRUM_REPO_DIR:-$HOME/spectrum}"
export PATH="$HOME/.local/bin:$PATH"

cd "$repo_dir"

if [ ! -d acquisition/.venv ]; then
  if python3 -m venv acquisition/.venv 2>/dev/null; then
    :
  elif python3 -m virtualenv acquisition/.venv; then
    :
  else
    python3 -m pip install --user --break-system-packages virtualenv
    python3 -m virtualenv acquisition/.venv
  fi
fi

acquisition/.venv/bin/python -m pip install --upgrade pip setuptools wheel
acquisition/.venv/bin/python -m pip install -e sdk/python
acquisition/.venv/bin/python -m pip install -e "acquisition[dev,hardware]"

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo "node/npm not found in PATH. Install Node.js under ~/.local/bin before Web UI setup." >&2
  exit 1
fi

npm install

acquisition/.venv/bin/python -c "import h1_sdk; print('h1_sdk ok')"
acquisition/.venv/bin/python -c "import pyrealsense2 as rs; print('pyrealsense2 ok')"
PATH="$HOME/.local/bin:$PATH" npm run build:webui
