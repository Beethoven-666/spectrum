"""Real H1 spectrometer adapter with a persistent serial connection.

The adapter imports ``h1_sdk`` lazily so acquisition mock mode works on hosts
where only the service skeleton is installed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, replace
from typing import Any, Iterator

from spectrum_acq.models import DeviceStatus, H1AutoExposureConfig, utc_now_iso

from .h1_cie import cie_mode_from_name, cie_mode_name
from .h1_serialize import spectrum_frame_to_json
from .interfaces import H1Capture, H1ExposureAttempt, H1ExposureFrame, H1Status

logger = logging.getLogger(__name__)


class H1DeviceAdapter:
    def __init__(self, port: str, *, timeout_s: float = 5.0) -> None:
        self.port = port
        self.timeout_s = timeout_s
        self._device: Any | None = None

    def _ensure_device(self) -> Any:
        if self._device is not None:
            return self._device
        from h1_sdk import Device

        self._device = Device(self.port, timeout=self.timeout_s)
        return self._device

    def _reset_device(self) -> None:
        if self._device is None:
            return
        try:
            self._device.close()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass
        self._device = None

    def status(self) -> H1Status:
        try:
            return self._status_from_device(self._ensure_device())
        except Exception as exc:  # noqa: BLE001 - hardware status should report failures
            self._reset_device()
            return H1Status(
                status=DeviceStatus.ERROR,
                serial_number=None,
                wavelength_range=None,
                exposure_time_us=None,
                detail={"port": self.port, "error": str(exc)},
            )

    def _call_device(self, fn):
        try:
            return fn(self._ensure_device())
        except Exception:
            self._reset_device()
            raise

    def device_info(self) -> dict[str, Any]:
        def work(dev: Any) -> dict[str, Any]:
            info = dev.get_device_info()
            wavelength_range = dev.get_wavelength_range()
            return {
                "serialNumber": info.serial_number.strip(),
                "wavelengthRange": {"start": wavelength_range.start, "end": wavelength_range.end},
            }

        return self._call_device(work)

    def get_exposure(self) -> dict[str, Any]:
        from h1_sdk.types import ExposureMode

        # Route through _call_device so a dead serial handle is dropped (and
        # re-opened on the next call) instead of being reused forever.
        def work(dev: Any) -> dict[str, Any]:
            mode = dev.get_exposure_mode()
            return {
                "mode": "auto" if mode == ExposureMode.Auto else "manual",
                "timeUs": dev.get_exposure_time_us(),
                "maxTimeUs": dev.get_max_exposure_time_us(),
            }

        return self._call_device(work)

    def patch_exposure(
        self,
        *,
        mode: str | None = None,
        time_us: int | None = None,
        max_time_us: int | None = None,
    ) -> dict[str, Any]:
        from h1_sdk.types import ExposureMode

        def work(dev: Any) -> dict[str, Any]:
            if mode is not None:
                dev.set_exposure_mode(ExposureMode.Auto if mode == "auto" else ExposureMode.Manual)
            if time_us is not None:
                dev.set_exposure_time_us(int(time_us))
            if max_time_us is not None:
                dev.set_max_exposure_time_us(int(max_time_us))
            m = dev.get_exposure_mode()
            return {
                "mode": "auto" if m == ExposureMode.Auto else "manual",
                "timeUs": dev.get_exposure_time_us(),
                "maxTimeUs": dev.get_max_exposure_time_us(),
            }

        return self._call_device(work)

    def get_cie_mode(self) -> dict[str, str]:
        return self._call_device(lambda dev: {"mode": cie_mode_name(dev.get_cie_mode())})

    def set_cie_mode(self, mode_name: str) -> dict[str, str]:
        mode = cie_mode_from_name(mode_name)

        def work(dev: Any) -> dict[str, str]:
            dev.set_cie_mode(mode)
            return {"mode": cie_mode_name(dev.get_cie_mode())}

        return self._call_device(work)

    def set_working_mode(self, mode: str) -> dict[str, str]:
        from h1_sdk.types import WorkingMode

        def work(dev: Any) -> dict[str, str]:
            working = WorkingMode.Trigger if mode == "trigger" else WorkingMode.Streaming
            dev.set_working_mode(working)
            return {"mode": mode}

        return self._call_device(work)

    def enter_sleep(self) -> dict[str, Any]:
        self._call_device(lambda dev: dev.enter_sleep())
        return {"ok": True, "state": "sleeping"}

    def exit_sleep(self) -> dict[str, Any]:
        self._call_device(lambda dev: dev.exit_sleep())
        return {"ok": True, "state": "awake"}

    def capture_single_frame(self, *, include_tm30: bool = False) -> dict[str, Any]:
        def work(dev: Any) -> dict[str, Any]:
            wavelength_range = dev.get_wavelength_range()
            exposure_us = dev.get_exposure_time_us()
            frame = dev.capture_single(
                include_tm30=include_tm30,
                timeout=capture_timeout_s(exposure_us, self.timeout_s),
            )
            return spectrum_frame_to_json(frame, wavelength_range.start)

        return self._call_device(work)

    def upload_efficiency_curve(self, ratios: list[float]) -> dict[str, Any]:
        self._call_device(lambda dev: dev.upload_efficiency_curve(ratios))
        return {"ok": True, "count": len(ratios)}

    def verify_efficiency_curve(self) -> dict[str, Any]:
        self._call_device(lambda dev: dev.verify_and_compute_efficiency_curve())
        return {"ok": True}

    def reset_efficiency_curve(self) -> dict[str, Any]:
        self._call_device(lambda dev: dev.reset_efficiency_curve())
        return {"ok": True}

    def capture_auto(self, config: H1AutoExposureConfig) -> H1Capture:
        # Route through _call_device: a hard pyserial error anywhere in the
        # capture (status read, convergence, restore) drops the dead handle so
        # the next call re-opens the port instead of reusing a broken one.
        def work(dev: Any) -> H1Capture:
            status = self._status_from_device(dev)
            if status.status != DeviceStatus.READY:
                raise RuntimeError(status.detail.get("error", "H1 device is not ready"))
            return self._capture_auto_with_device(dev, config, status=status)

        return self._call_device(work)

    def _status_from_device(self, dev: Any) -> H1Status:
        info = dev.get_device_info()
        wavelength_range = dev.get_wavelength_range()
        exposure_time_us = dev.get_exposure_time_us()
        try:
            exposure_mode = dev.get_exposure_mode().name.lower()
        except Exception:
            exposure_mode = None
        try:
            max_exposure_time_us = dev.get_max_exposure_time_us()
        except Exception:
            max_exposure_time_us = None
        return H1Status(
            status=DeviceStatus.READY,
            serial_number=info.serial_number.strip(),
            wavelength_range={"start": wavelength_range.start, "end": wavelength_range.end},
            exposure_time_us=exposure_time_us,
            exposure_mode=exposure_mode,
            max_exposure_time_us=max_exposure_time_us,
            detail={"port": self.port},
        )

    def _capture_auto_with_device(
        self,
        dev: Any,
        config: H1AutoExposureConfig,
        *,
        status: H1Status | None = None,
    ) -> H1Capture:
        active_status = status or self._status_from_device(dev)
        # Remember the operator's exposure mode. Sample capture always drives the
        # device internally (native auto for the first shot, manual for refinement),
        # but it must not silently leave the device flipped from what the UI set.
        original_mode = active_status.exposure_mode
        effective_config = self._apply_device_max_exposure(dev, config)

        pairs: list[tuple[H1ExposureAttempt, Any]] = []
        selected_index = 0
        with_frames = config.mode == "multi_exposure"
        try:
            if with_frames:
                pairs, selected_index = self._run_multi_exposure(
                    dev, effective_config, active_status
                )
            else:
                pairs = self._run_converge(dev, effective_config, active_status)
                selected_index = select_index([a.exposure_status for a, _ in pairs])
        finally:
            self._restore_exposure_mode(dev, original_mode)

        if not pairs:
            raise RuntimeError("H1 capture did not produce a frame")
        return self._build_capture(
            dev, pairs, selected_index, active_status, with_frames=with_frames
        )

    def _apply_device_max_exposure(
        self, dev: Any, config: H1AutoExposureConfig
    ) -> H1AutoExposureConfig:
        """Push the max-exposure cap (CMD 0x13) and clamp config to the device limit.

        The cap is honoured by the device's native auto-exposure, which attempt #1
        relies on, so it must be set before capturing.
        """
        try:
            dev.set_max_exposure_time_us(config.max_exposure_us)
        except Exception:
            pass
        try:
            device_max_us = int(dev.get_max_exposure_time_us())
            if device_max_us > 0:
                return replace(
                    config, max_exposure_us=min(config.max_exposure_us, device_max_us)
                )
        except Exception:
            pass
        return config

    def _restore_exposure_mode(self, dev: Any, original_mode: str | None) -> None:
        from h1_sdk.types import ExposureMode

        target = ExposureMode.Auto if original_mode == "auto" else ExposureMode.Manual
        try:
            dev.set_exposure_mode(target)
        except Exception:
            pass

    def _capture_at(
        self, dev: Any, idx: int, *, set_exposure_us: int | None, timeout_hint_us: int
    ) -> tuple[H1ExposureAttempt, Any]:
        """Capture one frame.

        ``set_exposure_us=None`` keeps the device's current (auto-chosen) exposure
        instead of forcing a manual value.
        """
        started = utc_now_iso()
        t0 = time.monotonic()
        if set_exposure_us is not None:
            dev.set_exposure_time_us(int(set_exposure_us))
        frame = dev.capture_single(
            include_tm30=False,
            timeout=capture_timeout_s(timeout_hint_us, self.timeout_s),
        )
        ended = utc_now_iso()
        attempt = H1ExposureAttempt(
            attempt=idx,
            exposure_time_us=int(frame.exposure_time_us),
            exposure_status=frame.exposure_status.name.lower(),
            started_at=started,
            ended_at=ended,
            duration_ms=(time.monotonic() - t0) * 1000.0,
        )
        return attempt, frame

    def _run_converge(
        self, dev: Any, config: H1AutoExposureConfig, active_status: H1Status
    ) -> list[tuple[H1ExposureAttempt, Any]]:
        """Find a well-exposed frame.

        Attempt #1 uses the device's documented native auto-exposure (CMD
        0x0A=Auto): the firmware lands close to correct in a single shot. If that
        frame is not ``normal`` (or auto is unsupported) we refine in manual mode,
        bracketing the target and bisecting between the under/over bounds so the
        search converges instead of oscillating on fixed multipliers.
        """
        from h1_sdk.types import ExposureMode

        max_attempts = max(config.max_attempts, 1)
        pairs: list[tuple[H1ExposureAttempt, Any]] = []
        under_bound: int | None = None  # highest exposure seen UNDER (target is higher)
        over_bound: int | None = None  # lowest exposure seen OVER (target is lower)

        used_auto = False
        next_exposure_us: int | None
        try:
            dev.set_exposure_mode(ExposureMode.Auto)
            used_auto = True
            next_exposure_us = None  # let the device choose
        except Exception:
            next_exposure_us = clamp_exposure_us(
                active_status.exposure_time_us or config.initial_exposure_us, config
            )

        converged = False
        # Count of manual refinement steps already taken. After the first one we
        # let the search seed a missing bracket bound from the config limits so a
        # far-off native-auto pick still converges via geometric bisection.
        refinements = 0
        for idx in range(1, max_attempts + 1):
            if idx == 2 and used_auto:
                # Hand off from native auto to deterministic manual refinement.
                try:
                    dev.set_exposure_mode(ExposureMode.Manual)
                except Exception:
                    pass
            timeout_hint = (
                next_exposure_us if next_exposure_us is not None else config.max_exposure_us
            )
            attempt, frame = self._capture_at(
                dev, idx, set_exposure_us=next_exposure_us, timeout_hint_us=timeout_hint
            )
            pairs.append((attempt, frame))
            status = attempt.exposure_status
            if status == "normal":
                converged = True
                break

            exposure_us = clamp_exposure_us(attempt.exposure_time_us, config)
            if status == "under":
                under_bound = exposure_us if under_bound is None else max(under_bound, exposure_us)
            elif status == "over":
                over_bound = exposure_us if over_bound is None else min(over_bound, exposure_us)

            # After the first refinement step, seed the missing bracket bound from
            # the config limits so geometric bisection engages even when only one
            # of under/over has been seen.
            nxt = next_exposure_time_us(
                exposure_us,
                status,
                config,
                under_bound=under_bound,
                over_bound=over_bound,
                seed_missing_bound=refinements >= 1,
            )
            refinements += 1
            if nxt == exposure_us:
                # Clamped at a limit / bracket collapsed — no better exposure to try.
                break
            next_exposure_us = nxt

        if not converged:
            # Surface a signal so callers/operators can see the auto-exposure
            # search ran out of attempts without landing a ``normal`` frame.
            last_status = pairs[-1][0].exposure_status if pairs else "none"
            last_exposure = pairs[-1][0].exposure_time_us if pairs else None
            logger.warning(
                "h1_exposure_not_converged: port=%s attempts=%d last_status=%s "
                "last_exposure_us=%s under_bound=%s over_bound=%s",
                self.port,
                len(pairs),
                last_status,
                last_exposure,
                under_bound,
                over_bound,
            )

        return pairs

    def _run_multi_exposure(
        self, dev: Any, config: H1AutoExposureConfig, active_status: H1Status
    ) -> tuple[list[tuple[H1ExposureAttempt, Any]], int]:
        """Capture a ladder of exposures around the auto-chosen centre and keep
        every spectrum for offline study (design §6 ``multi_exposure``)."""
        from h1_sdk.types import ExposureMode

        converge = self._run_converge(dev, config, active_status)
        center_index = select_index([a.exposure_status for a, _ in converge])
        center_us = converge[center_index][0].exposure_time_us

        try:
            dev.set_exposure_mode(ExposureMode.Manual)
        except Exception:
            pass

        captured: dict[int, tuple[H1ExposureAttempt, Any]] = {
            a.exposure_time_us: (a, f) for a, f in converge
        }
        idx = len(converge)
        for factor in ladder_factors(config.multi_exposure_steps):
            target = clamp_exposure_us(int(round(center_us * factor)), config)
            if target in captured:
                continue
            idx += 1
            attempt, frame = self._capture_at(
                dev, idx, set_exposure_us=target, timeout_hint_us=target
            )
            captured[attempt.exposure_time_us] = (attempt, frame)

        pairs = sorted(captured.values(), key=lambda p: p[0].exposure_time_us)
        statuses = [a.exposure_status for a, _ in pairs]
        exposures = [a.exposure_time_us for a, _ in pairs]
        selected_index = select_index(statuses, center_us=center_us, exposure_times=exposures)
        return pairs, selected_index

    def _build_capture(
        self,
        dev: Any,
        pairs: list[tuple[H1ExposureAttempt, Any]],
        selected_index: int,
        active_status: H1Status,
        *,
        with_frames: bool,
    ) -> H1Capture:
        marked_attempts: list[H1ExposureAttempt] = []
        frames: list[H1ExposureFrame] = []
        for i, (attempt, frame) in enumerate(pairs):
            marked = replace(attempt, attempt=i + 1, selected=i == selected_index)
            marked_attempts.append(marked)
            if with_frames:
                frames.append(
                    H1ExposureFrame(
                        attempt=i + 1,
                        exposure_time_us=marked.exposure_time_us,
                        exposure_status=marked.exposure_status,
                        spectrum_coefficient=frame.spectrum_coefficient,
                        raw_spectrum=list(frame.raw_spectrum),
                        actual_spectrum=list(frame.actual_spectrum),
                        selected=i == selected_index,
                    )
                )

        selected_frame = pairs[selected_index][1]
        try:
            dev.set_exposure_time_us(int(marked_attempts[selected_index].exposure_time_us))
        except Exception:
            pass

        wavelength_start = (
            active_status.wavelength_range["start"] if active_status.wavelength_range else 0
        )
        wavelengths = list(
            range(wavelength_start, wavelength_start + len(selected_frame.raw_spectrum))
        )
        final_status = self._status_from_device(dev)
        return H1Capture(
            status=final_status,
            selected_attempt=marked_attempts[selected_index],
            attempts=marked_attempts,
            wavelengths=wavelengths,
            raw_spectrum=list(selected_frame.raw_spectrum),
            actual_spectrum=list(selected_frame.actual_spectrum),
            photometric=asdict(selected_frame.photometric),
            plant=asdict(selected_frame.plant),
            spectrum_coefficient=selected_frame.spectrum_coefficient,
            frames=frames,
        )

    def _enable_stream_auto_exposure(self, dev: Any, config: H1AutoExposureConfig) -> int:
        """Put the device in native auto-exposure with a preview-friendly cap.

        For a LIVE stream we let the firmware adjust exposure per frame (CMD
        0x0A=Auto, capped by 0x13) instead of running a blocking software
        convergence first — that did several full-exposure captures before the
        first frame, stalling the stream and holding the device lock for tens of
        seconds at long exposures. Returns the cap actually applied (µs).
        """
        from h1_sdk.types import ExposureMode

        cap_us = max(
            config.min_exposure_us,
            min(config.max_exposure_us, config.stream_max_exposure_us),
        )
        try:
            dev.set_max_exposure_time_us(cap_us)
        except Exception:
            pass
        try:
            device_max_us = int(dev.get_max_exposure_time_us())
            if device_max_us > 0:
                cap_us = min(cap_us, device_max_us)
        except Exception:
            pass
        # Pin the current exposure down to the cap BEFORE enabling auto, so the
        # first streamed frame isn't taken at a stale (possibly multi-second)
        # manual exposure left over from a previous capture.
        try:
            dev.set_exposure_time_us(cap_us)
        except Exception:
            pass
        try:
            dev.set_exposure_mode(ExposureMode.Auto)
        except Exception:
            pass
        return cap_us

    def stream(
        self,
        *,
        include_tm30: bool = False,
        max_frames: int | None = None,
        config: H1AutoExposureConfig | None = None,
    ) -> Iterator[dict[str, Any]]:
        # Reset the device handle on ANY exception escaping the generator (a hard
        # pyserial error during setup or mid-stream) so a dead handle isn't
        # reused on the next stream/capture. The whole generator runs on a single
        # thread (driven by the SSE bridge), so _reset_device() — including the
        # SDK's RLock release inside dev.close() — stays on the acquiring thread.
        try:
            dev = self._ensure_device()
            wavelength_range = dev.get_wavelength_range()
            frame_timeout = self.timeout_s
            # Default stop-drain covers a trailing frame at the base timeout.
            stop_drain_s = 1.0
            if config is not None:
                cap_us = self._enable_stream_auto_exposure(dev, config)
                frame_timeout = capture_timeout_s(cap_us, self.timeout_s)
                # A trailing frame starts arriving ~one exposure (cap) after the
                # stop; drain a little longer than that so it's consumed before
                # the next cmd.
                stop_drain_s = (cap_us / 1_000_000.0) + 0.4
            for frame in dev.stream(
                include_tm30=include_tm30,
                max_frames=max_frames,
                frame_timeout=frame_timeout,
                stop_drain_s=stop_drain_s,
            ):
                yield spectrum_frame_to_json(frame, wavelength_range.start)
        except Exception:
            self._reset_device()
            raise


def spectrum_frame_to_stream_payload(frame: Any, wavelength_start: int) -> dict[str, Any]:
    """Backward-compatible alias."""
    return spectrum_frame_to_json(frame, wavelength_start)


def clamp_exposure_us(value: int, config: H1AutoExposureConfig) -> int:
    return max(config.min_exposure_us, min(int(value), config.max_exposure_us))


def capture_timeout_s(exposure_us: int, base_timeout_s: float) -> float:
    return max(base_timeout_s, (int(exposure_us) / 1_000_000.0) + 10.0)


def next_exposure_time_us(
    exposure_us: int,
    exposure_status: str,
    config: H1AutoExposureConfig,
    *,
    under_bound: int | None = None,
    over_bound: int | None = None,
    seed_missing_bound: bool = False,
) -> int:
    # Once the target is bracketed (we have seen both an under and an over
    # exposure), bisect geometrically between the bounds. This converges in a few
    # steps instead of oscillating on the fixed under/over multipliers.
    if under_bound is not None and over_bound is not None and over_bound > under_bound:
        return clamp_exposure_us(int(round((under_bound * over_bound) ** 0.5)), config)

    # Not yet bracketed. From a far-off native-auto pick the fixed under/over
    # multipliers can't traverse the whole range inside ``max_attempts``, so a
    # bracket may never form. When the caller asks (after the first manual
    # refinement step), seed the still-missing bound from the config exposure
    # limits and bisect geometrically — this engages binary search and converges
    # in ~log2(range) steps regardless of how far off the starting point is.
    if seed_missing_bound and (under_bound is None) != (over_bound is None):
        if under_bound is None and exposure_status == "over":
            # Target is below ``exposure_us``; the floor can't be over, so the
            # lowest possible exposure is a safe under bound.
            lo = config.min_exposure_us
            hi = over_bound if over_bound is not None else exposure_us
            if hi > lo:
                return clamp_exposure_us(int(round((lo * hi) ** 0.5)), config)
        if over_bound is None and exposure_status == "under":
            # Target is above ``exposure_us``; the ceiling can't be under, so the
            # highest possible exposure is a safe over bound.
            lo = under_bound if under_bound is not None else exposure_us
            hi = config.max_exposure_us
            if hi > lo:
                return clamp_exposure_us(int(round((lo * hi) ** 0.5)), config)

    if exposure_status == "under":
        return clamp_exposure_us(int(exposure_us * config.under_multiplier), config)
    if exposure_status == "over":
        return clamp_exposure_us(int(exposure_us * config.over_multiplier), config)
    return clamp_exposure_us(exposure_us, config)


def ladder_factors(steps: int) -> list[float]:
    """Geometric multipliers around 1.0 for the multi-exposure ladder.

    The centred ``1.0x`` rung (the auto-chosen exposure) is ALWAYS included. For
    an odd ``steps`` the rungs are symmetric about 1.0x. For an even ``steps`` we
    keep the same one-octave-per-rung spacing but anchor a rung at exactly 1.0x
    (slightly more headroom above than below), so the auto-chosen exposure is
    never skipped.

    ``steps=5`` -> ``[0.25, 0.5, 1.0, 2.0, 4.0]``; ``steps=1`` -> ``[1.0]``;
    ``steps=4`` -> ``[0.5, 1.0, 2.0, 4.0]`` (1.0x present).
    """
    steps = max(int(steps), 1)
    if steps == 1:
        return [1.0]
    if steps % 2 == 1:
        span = 2.0  # +-2 octaves at the ends (x0.25 .. x4) for the canonical 5
        half = (steps - 1) / 2.0
        return [2.0 ** (span * (i - half) / half) for i in range(steps)]
    # Even count: one octave per rung, anchored so index ``steps // 2 - 1`` is
    # exactly 1.0x. This guarantees the centred rung is present.
    center_idx = steps // 2 - 1
    return [2.0 ** float(i - center_idx) for i in range(steps)]


def select_index(
    statuses: list[str],
    *,
    center_us: int | None = None,
    exposure_times: list[int] | None = None,
) -> int:
    """Pick the frame to keep.

    Prefer the first ``normal`` frame; otherwise the frame nearest the auto-chosen
    centre (when known, for the multi-exposure ladder); otherwise the last (most
    refined) attempt.
    """
    if not statuses:
        return 0
    for i, status in enumerate(statuses):
        if status == "normal":
            return i
    if center_us is not None and exposure_times:
        return min(
            range(len(exposure_times)),
            key=lambda i: abs(exposure_times[i] - center_us),
        )
    return len(statuses) - 1
