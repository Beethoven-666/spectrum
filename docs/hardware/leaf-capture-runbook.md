# Leaf capture runbook

This is the operator runbook for the Raspberry Pi 5 at
`croprix-spectrum.local`.

## Current hardware

- Raspberry Pi 5 4GB, Ubuntu 24.04 ARM64.
- RealSense D455F/D455i on USB3, serial `419122302660`.
- H1 spectrometer through CH340 at
  `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`.
- Main RGB camera is intentionally missing until the cable arrives.

## Start services

Stop the old patrol camera push before acquisition, otherwise `ffmpeg` owns
`/dev/video0` and D455 capture fails:

```bash
ssh croprix-spectrum.local
systemctl --user stop patrol-camera-push.service
```

Start the Python acquisition API on loopback:

```bash
cd ~/spectrum
PATH=$HOME/.local/bin:$PATH acquisition/.venv/bin/spectrum-acq \
  --data-dir ./data \
  --hardware \
  --host 127.0.0.1 \
  --port 8000
```

Start the Web UI on the LAN:

```bash
cd ~/spectrum
PATH=$HOME/.local/bin:$PATH ACQUISITION_API_BASE_URL=http://127.0.0.1:8000 \
  npm run dev -w h1-webui -- --hostname 0.0.0.0 --port 3005
```

Open:

```text
http://croprix-spectrum.local:3005/acquisition
```

For a repeatable development start, run:

```bash
cd ~/spectrum
scripts/pi_start_capture_stack.sh
```

To stop the development stack:

```bash
cd ~/spectrum
scripts/pi_stop_capture_stack.sh
```

User-level systemd templates are available in `deploy/systemd/user/`. They are
not enabled automatically; install them only when the development flow is stable
enough to run on boot.

If `acquisition/.venv` or `node_modules` are missing, rebuild the development
environment with:

```bash
cd ~/spectrum
scripts/pi_setup_dev.sh
```

## Smoke tests

Run these on the Pi:

```bash
cd ~/spectrum
acquisition/.venv/bin/python -m pytest acquisition
acquisition/.venv/bin/python scripts/pi_h1_smoke.py
acquisition/.venv/bin/python scripts/pi_d455_smoke.py
PATH=$HOME/.local/bin:$PATH npm run build:webui
```

Run these from the Mac or the Pi while both services are up:

```bash
curl -sS http://croprix-spectrum.local:3005/api/acquisition/health
curl -sS http://croprix-spectrum.local:3005/api/acquisition/devices
curl -sS -X POST http://croprix-spectrum.local:3005/api/acquisition/capture \
  -H 'Content-Type: application/json' \
  -d '{}'
curl -sS -X POST http://croprix-spectrum.local:3005/api/acquisition/samples/export
```

Rebuild the SQLite query cache from the sample directories:

```bash
cd ~/spectrum
acquisition/.venv/bin/spectrum-acq rebuild-index --data-dir ./data
```

## Sample layout

Hardware samples are written under `~/spectrum/data/samples/<sample_id>/`.
A complete v1 sample contains:

- `metadata.json`
- `quality.json`
- `h1/spectrum.json`
- `h1/spectrum.csv`
- `h1/exposure_attempts.json`
- `d455/color.jpg`
- `d455/depth.png`
- `d455/depth.npy`
- `d455/imu.json`
- `d455/pointcloud_full.ply`
- `d455/pointcloud_roi.ply`
- `roi/roi.json`
- `roi/preview.jpg`
- `main_rgb/status.json`

SQLite is only the query index at `~/spectrum/data/index/samples.sqlite3`; the
sample directory remains the source of truth.

## Known hardware notes

- D455 color/depth and point cloud capture work on the current Pi.
- D455 IMU currently reports a Linux IIO permission error. The acquisition
  service records that error and continues without IMU data.
- H1 currently returns `Under` in the test scene even after three conservative
  exposure attempts. The sample is saved with `quality_status=warn`.
- `strict` H1 exposure mode rejects non-`normal` captures unless `force` is set.
- The current SD card has roughly 5.5GB free after dependencies and two
  hardware samples. Move `data/` to USB SSD before bulk collection.
