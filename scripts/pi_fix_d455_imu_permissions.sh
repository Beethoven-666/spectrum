#!/usr/bin/env bash
# Grant RealSense D455 Linux IIO (accel/gyro) access to plugdev users.
set -euo pipefail

RULE=/etc/udev/rules.d/99-realsense-iio.rules

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

# Group-own the matching RealSense IIO device tree by "plugdev" and make it
# group read/write, rather than world-writable (a+rw). The udev MODE/GROUP only
# applies to the device node itself, so the RUN line recurses group ownership
# and the group-writable bit over the buffer/scan_elements sub-attributes that
# libusb/IIO needs, without exposing them to every local user.
cat >"$RULE" <<'EOF'
# Intel RealSense D455/D455f IMU via Linux IIO
SUBSYSTEM=="iio", KERNEL=="iio:device*", ATTRS{idVendor}=="8086", ATTRS{idProduct}=="0b5c", MODE="0660", GROUP="plugdev", TAG+="uaccess", RUN+="/bin/sh -c 'chgrp -R plugdev /sys$env{DEVPATH} && chmod -R g+rw /sys$env{DEVPATH}'"
EOF
chmod 644 "$RULE"
udevadm control --reload-rules
udevadm trigger --subsystem-match=iio

# Apply the same scoped permissions immediately to the RealSense IIO device(s)
# already present, so a re-plug/reboot is not required. Match on the USB
# vendor:product so we never touch unrelated IIO devices on the bus.
for dev in /sys/bus/iio/devices/iio:device*; do
  [ -e "$dev" ] || continue
  # Resolve the device's USB ids; skip anything that is not the D455 (8086:0b5c).
  vid="$(cat "$dev"/../../../idVendor 2>/dev/null || true)"
  pid="$(cat "$dev"/../../../idProduct 2>/dev/null || true)"
  if [ "$vid" != "8086" ] || [ "$pid" != "0b5c" ]; then
    continue
  fi
  chgrp -R plugdev "$dev"
  chmod -R g+rw "$dev"
done

echo "Installed $RULE and refreshed IIO permissions."
echo "If IMU still fails, reset the camera once: sudo usbreset 8086:0b5c"
