# croprix-spectrum environment

Captured on 2026-05-31 during implementation and updated after the first
hardware capture.

## Host

```text
PRETTY_NAME="Ubuntu 24.04.4 LTS"
VERSION_CODENAME=noble
Linux croprix-spectrum 6.8.0-1053-raspi #57-Ubuntu SMP PREEMPT_DYNAMIC Wed Apr 15 06:45:56 UTC 2026 aarch64
```

## USB devices

```text
Bus 004 Device 003: ID 1a86:7523 QinHeng Electronics CH340 serial converter
Bus 005 Device 002: ID 8086:0b5c Intel Corp. Intel(R) RealSense(TM) Depth Camera 455f
```

D455 is on a 5000M USB3 root hub:

```text
/:  Bus 005.Port 001: Dev 001, Class=root_hub, Driver=xhci-hcd/1p, 5000M
    |__ Port 001: Dev 002, If 0, Class=Video, Driver=uvcvideo, 5000M
    |__ Port 001: Dev 002, If 1, Class=Video, Driver=uvcvideo, 5000M
    |__ Port 001: Dev 002, If 2, Class=Video, Driver=uvcvideo, 5000M
    |__ Port 001: Dev 002, If 3, Class=Video, Driver=uvcvideo, 5000M
    |__ Port 001: Dev 002, If 4, Class=Video, Driver=uvcvideo, 5000M
    |__ Port 001: Dev 002, If 5, Class=Human Interface Device, Driver=usbhid, 5000M
```

H1 is visible through the CH340 serial adapter:

```text
/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 -> ../../ttyUSB0
```

## Runtime status

```text
Python 3.12.3
acquisition/.venv: created with virtualenv
pyrealsense2: installed in acquisition/.venv
node: v24.16.0 at ~/.local/bin/node
npm: 11.13.0 at ~/.local/bin/npm
h1-sdk: installed editable from sdk/python
```

The `ray` user has the relevant hardware groups:

```text
ray adm dialout cdrom sudo audio video plugdev games users netdev render input gpio spi i2c
```

## Storage

```text
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2   15G  8.0G  5.5G  60% /
Mem:           3.9Gi       1.3Gi       282Mi       5.4Mi       2.4Gi       2.6Gi
Swap:          2.0Gi          0B       2.0Gi
```

This SD-card root filesystem is adequate for smoke tests only. Full point cloud
capture should move `data/` to a USB SSD before bulk collection.

## Hardware smoke results

H1 smoke passed:

```text
serial: H11B6V10534FFPD-211-0021
wavelength_range: 340 1050
exposure_mode: Manual
max_exposure_time_us: 1000000
exposure_status: Under
exposure_time_us: 144500
raw_points: 711
```

D455 color/depth smoke passed after stopping the user camera-push service:

```text
devices: 1
name: Intel RealSense D455F
serial: 419122302660
firmware: 5.15.1.55
depth_scale: 0.0010000000474974513
depth: 640 480 frame 3
color: 640 480 frame 1
```

`patrol-camera-push.service` was using `/dev/video0` through `ffmpeg` and
caused `xioctl(VIDIOC_S_FMT) failed, errno=16 Last Error: Device or resource
busy`. Keep it stopped while `spectrum-acq` owns the D455:

```bash
systemctl --user stop patrol-camera-push.service
```

The D455 IMU currently fails through Linux IIO permissions:

```text
Failed to open scan_element .../iio:device1/scan_elements/in_anglvel_x_en Last Error: Permission denied
```

The acquisition service falls back to color/depth capture and writes this IMU
error into each sample's `d455/imu.json`.

## Verified services

The current verified runtime shape is:

```text
spectrum-acq: 127.0.0.1:8000
Next.js Web UI: 0.0.0.0:3005
Operator URL: http://croprix-spectrum.local:3005/acquisition
```

Verified hardware samples include:

```text
20260530T222043493Z_128284
20260530T222339139Z_5b7692
20260530T225403896Z_4a132d
```

Each sample contains H1 spectrum JSON/CSV, D455 color/depth, full and ROI PLY
point clouds, ROI preview, metadata, quality report, and `main_rgb/status.json`
with the expected `missing` status until the RGB camera cable arrives.
