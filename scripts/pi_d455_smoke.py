#!/usr/bin/env python3
"""Minimal D455 smoke test for croprix-spectrum.local."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import pyrealsense2 as rs
    except ImportError as exc:
        print(f"pyrealsense2 import failed: {exc}", file=sys.stderr)
        return 2

    ctx = rs.context()
    devices = ctx.query_devices()
    print(f"devices: {len(devices)}")
    for dev in devices:
        print("name:", dev.get_info(rs.camera_info.name))
        print("serial:", dev.get_info(rs.camera_info.serial_number))
        print("firmware:", dev.get_info(rs.camera_info.firmware_version))

    pipeline = rs.pipeline()
    config = build_config(rs, include_imu=True)
    imu_enabled = True
    try:
        profile = pipeline.start(config)
    except Exception as exc:  # noqa: BLE001 - smoke test should print hardware access failures
        print("imu: unavailable", exc)
        pipeline = rs.pipeline()
        profile = pipeline.start(build_config(rs, include_imu=False))
        imu_enabled = False
    try:
        depth_sensor = profile.get_device().first_depth_sensor()
        print("depth_scale:", depth_sensor.get_depth_scale())
        frames = pipeline.wait_for_frames(5000)
        depth = frames.get_depth_frame()
        color = frames.get_color_frame()
        print("depth:", depth.get_width(), depth.get_height(), "frame", depth.get_frame_number())
        print("color:", color.get_width(), color.get_height(), "frame", color.get_frame_number())
        print_motion_frame(rs, frames, "accel")
        print_motion_frame(rs, frames, "gyro")
        if not imu_enabled:
            print("imu: disabled for color/depth smoke")
    finally:
        pipeline.stop()
    return 0


def build_config(rs, *, include_imu: bool):
    config = rs.config()
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)
    config.enable_stream(rs.stream.color, 640, 480, rs.format.rgb8, 15)
    if include_imu:
        config.enable_stream(rs.stream.accel)
        config.enable_stream(rs.stream.gyro)
    return config


def print_motion_frame(rs, frames, name: str) -> None:
    stream = getattr(rs.stream, name)
    frame = frames.first_or_default(stream)
    if not frame:
        print(f"{name}: missing")
        return
    motion = frame.as_motion_frame().get_motion_data()
    print(f"{name}:", frame.get_timestamp(), motion.x, motion.y, motion.z)


if __name__ == "__main__":
    raise SystemExit(main())
