#!/usr/bin/env bash
# Grant RealSense D455 Linux IIO (accel/gyro) access to plugdev users.
set -euo pipefail

RULE=/etc/udev/rules.d/99-realsense-iio.rules

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

cat >"$RULE" <<'EOF'
# Intel RealSense D455/D455f IMU via Linux IIO
SUBSYSTEM=="iio", KERNEL=="iio:device*", ATTRS{idVendor}=="8086", ATTRS{idProduct}=="0b5c", MODE="0660", GROUP="plugdev", TAG+="uaccess", RUN+="/bin/sh -c 'chmod -R a+rw /sys$env{DEVPATH}'"
EOF
chmod 644 "$RULE"
udevadm control --reload-rules
udevadm trigger --subsystem-match=iio

for dev in /sys/bus/iio/devices/iio:device*; do
  [ -e "$dev" ] || continue
  chmod -R a+rw "$dev"
done

echo "Installed $RULE and refreshed IIO permissions."
echo "If IMU still fails, reset the camera once: sudo usbreset 8086:0b5c"
