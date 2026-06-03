# Post-audit follow-ups (deferred)

These items were surfaced by the comprehensive audit and **intentionally deferred** when
the audit fixes were applied (commit `0fe8699`, "apply comprehensive audit findings across
the stack"). They are tracked here rather than done because each needs an explicit decision,
a toolchain not present on the Pi, or real-hardware fault injection.

> Status of the audit fixes themselves: 48 verified findings (+ safe low-severity items)
> are implemented, committed to `main`, and deployed. Verified: acquisition pytest (74),
> SDK-python sync (79), webui `next build`, Node SDK `tsc`. See the audit report for the
> full finding list.

---

## 1. Turn on the API auth (currently default-OFF) — decision/config

The acquisition API now supports an env-gated bearer token (`spectrum_acq/api/auth.py`,
`require_token`), applied to all state-changing and file routes. It is **off by default**:
when `ACQUISITION_API_TOKEN` is unset/empty, every request is allowed (unchanged behavior).

To enforce it:

1. Choose a strong token, e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Set it in **both** services' environment (so the webui proxy can inject it):
   - `~/.config/systemd/user/spectrum-acq.service` → add `Environment=ACQUISITION_API_TOKEN=<token>`
   - `~/.config/systemd/user/spectrum-webui.service` → add `Environment=ACQUISITION_API_TOKEN=<token>`
     (the webui proxy at `webui/src/app/api/acquisition/[...path]/route.ts` reads
     `process.env.ACQUISITION_API_TOKEN` and adds `Authorization: Bearer <token>` to forwarded
     requests; keep the value server-side only — never expose it to the browser).
   - Keep the matching change in the repo `deploy/systemd/user/*.service` too.
3. `systemctl --user daemon-reload && systemctl --user restart spectrum-acq spectrum-webui`.
4. Verify: an unauthenticated `POST` to a mutating route now returns `401`, while the webui
   (which injects the token) keeps working.

Note: the acquisition service binds `127.0.0.1`; the token primarily protects against the
LAN-exposed webui proxy (`0.0.0.0:3005`) being used cross-origin to drive the hardware (audit
finding H1). Enabling auth is the recommended posture if the rig is on a shared network.

## 2. Compile-verify the C++ and ESP32 SDK changes — needs a toolchain

The audit fixes edited two SDKs that **could not be compiled on the Pi** (no `cmake`,
no ESP-IDF):

- `sdk/cpp/src/Framing.cpp` — added a header resync loop in `readFrame` (finding M9).
- `sdk/esp32/h1_minimal/h1_minimal.ino` — fixed the spectrum scale for a negative
  `spectrumCoefficient` via `powf(10, -N)` (finding M8).

Both are correct-by-construction but unverified. On a dev machine:

- C++: `cmake -S sdk/cpp -B sdk/cpp/build && cmake --build sdk/cpp/build` and run the
  doctest suite.
- ESP32: build `sdk/esp32/h1_minimal` with ESP-IDF / Arniono-ESP32 and smoke-test against a device.

## 3. Live-exercise the failure-mode recovery paths — needs fault injection

These fixes are covered by unit tests but were **not exercised against real hardware** (they
only trigger under genuine faults):

- **D455 brownout degraded capture** (M10, `capture/coordinator.py`): with `force=True`, a
  D455 `CameraTimeout` should yield a spectrum-only sample (geometry omitted, `quality=BAD`,
  `depth_unavailable` warning) instead of failing the capture. Exercise by inducing a D455
  timeout (e.g. unplug/brownout) during a forced capture.
- **Main-RGB stall timeout** (H3, `devices/main_rgb.py`): a silent UVC stall (pipe open, no
  bytes) should now time out and self-heal (reopen) rather than wedge the worker forever.
  Exercise by stalling/under-powering the main RGB camera mid-stream.
- **H1 serial handle reset on hard error** (M11, `devices/h1.py`): a mid-op pyserial fault
  (USB unplug) during `capture_auto`/`stream`/exposure ops should now reset and reopen on the
  next call rather than reuse a dead handle. Exercise by unplugging the H1 during a capture.

---

## Also still open (not in the fixed set)

The audit listed ~17 **low / low-confidence** findings that were passed through on severity
triage **without independent verification** (e.g. even-`multi_exposure_steps` rung, Node
`actualSpectrum` Float32 precision, device-info SN trailing-NUL handling across SDKs). These
were **not** fixed and should be confirmed before acting. See the audit report's
"LOW (unverified)" list.
