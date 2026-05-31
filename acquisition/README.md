# spectrum-acq

Python acquisition service for the Raspberry Pi leaf multimodal capture device.

The service owns hardware access for H1, RealSense D455, the future main RGB
camera, sample storage, SQLite indexing, and the FastAPI interface consumed by
the Next.js Web UI.

Development starts in mock mode:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ../sdk/python
pip install -e ".[dev]"
spectrum-acq --data-dir ./data --mock
```

On the Raspberry Pi after `pyrealsense2` and `h1-sdk` are available:

```bash
cd ~/spectrum
PATH=$HOME/.local/bin:$PATH acquisition/.venv/bin/spectrum-acq \
  --data-dir ./data \
  --hardware \
  --host 127.0.0.1 \
  --port 8000
```

The service is normally kept on loopback. The Next.js Web UI proxies browser
requests through `/api/acquisition/*`, so the public operator URL can be just
the Web UI:

```bash
cd ~/spectrum
PATH=$HOME/.local/bin:$PATH ACQUISITION_API_BASE_URL=http://127.0.0.1:8000 \
  npm run dev -w h1-webui -- --hostname 0.0.0.0 --port 3005
```

Useful hardware checks:

```bash
acquisition/.venv/bin/python scripts/pi_h1_smoke.py
acquisition/.venv/bin/python scripts/pi_d455_smoke.py
curl -sS http://127.0.0.1:8000/devices
curl -sS -X POST http://127.0.0.1:8000/capture -H 'Content-Type: application/json' -d '{}'
spectrum-acq rebuild-index --data-dir ./data
```

If `patrol-camera-push.service` is running, it owns `/dev/video0` through
`ffmpeg` and RealSense capture will fail with `Device or resource busy`.
Stop that user service before running acquisition:

```bash
systemctl --user stop patrol-camera-push.service
```

The D455 IMU may require additional Linux IIO permissions on Ubuntu 24.04.
When those permissions are missing, acquisition falls back to color/depth and
records the IMU error in `d455/imu.json`; point cloud and distance/angle
metrics still work.

`strict` H1 exposure mode rejects non-`normal` captures unless `force` is set.
`conservative` keeps the best attempt and records warnings, which is the safer
default for field collection.
