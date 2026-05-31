#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

out="${1:-docs/hardware/croprix-spectrum-env.md}"
mkdir -p "$(dirname "$out")"

{
  echo "# croprix-spectrum environment"
  echo
  echo "Generated at: $(date -Is)"
  echo
  echo "## OS"
  echo '```text'
  cat /etc/os-release || true
  uname -a || true
  echo '```'
  echo
  echo "## USB"
  echo '```text'
  lsusb || true
  echo
  lsusb -t || true
  echo '```'
  echo
  echo "## Devices"
  echo '```text'
  ls -l /dev/serial/by-id /dev/video* 2>/dev/null || true
  echo '```'
  echo
  echo "## Runtime"
  echo '```text'
  python3 --version || true
  command -v node && node --version || true
  command -v npm && npm --version || true
  python3 -c 'import pyrealsense2 as rs; print("pyrealsense2", rs.__version__)' 2>&1 || true
  acquisition/.venv/bin/python -c 'import pyrealsense2 as rs; print("venv pyrealsense2", getattr(rs, "__version__", "installed"))' 2>&1 || true
  echo '```'
  echo
  echo "## Storage and memory"
  echo '```text'
  df -h /
  free -h
  groups
  echo '```'
} > "$out"

echo "Wrote $out"
