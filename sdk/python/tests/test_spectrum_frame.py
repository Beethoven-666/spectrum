"""SpectrumFrame layout tests for PROTOCOL.md §9.4.

We build synthetic validData byte strings, feed them through
``decode_spectrum_frame``, and check each field lands at the right offset.
"""

from __future__ import annotations

import struct

import pytest

from h1_sdk import ExposureStatus
from h1_sdk.protocol import (
    Cmd,
    build_response_frame,
    decode_spectrum_frame,
    parse_frame,
)


def _build_valid_data(
    *,
    m: int = 711,
    include_tm30: bool = False,
    coefficient: int = 2,
    exposure_us: int = 2500,
    exposure_status: int = ExposureStatus.Normal,
) -> bytes:
    """Build a synthetic validData payload with predictable contents."""
    parts = []
    parts.append(bytes([exposure_status]))
    parts.append(struct.pack("<I", exposure_us))
    # photometric: 47 zeros except set a few sentinels at known indices to
    # verify ordering.
    photo = [0.0] * 47
    photo[0] = 1.0    # X
    photo[9] = 5000.0  # CCT
    photo[15] = 95.0   # Ra
    photo[38] = 120.0  # lux
    parts.append(struct.pack("<47f", *photo))
    # blueHazard: single float
    parts.append(struct.pack("<f", 0.7))
    # nir: 3 floats
    parts.append(struct.pack("<3f", 1.1, 2.2, 3.3))
    # plant: 16 floats, set PAR + PPFD to known sentinels
    plant = [0.0] * 16
    plant[0] = 42.0   # PAR
    plant[7] = 800.0  # PPFD
    parts.append(struct.pack("<16f", *plant))
    if include_tm30:
        tm30 = [0.0] * 614
        tm30[0] = 11.0          # referenceSpectrum[0]
        tm30[400] = 12.0        # referenceSpectrum[400]
        tm30[401] = 13.0        # Eab[0]
        tm30[499] = 14.0        # Eab[98]
        tm30[500] = 90.0        # Rf
        tm30[501] = 105.0       # Rg
        tm30[502] = 1.5         # chromaShift[0]
        tm30[517] = 2.5         # chromaShift[15]
        tm30[550] = 0.11        # cesAbTest[0][a]
        tm30[551] = 0.22        # cesAbTest[0][b]
        tm30[612] = 7.7         # cesAbReference[15][a]
        tm30[613] = 8.8         # cesAbReference[15][b]
        parts.append(struct.pack("<614f", *tm30))
    parts.append(struct.pack("<h", coefficient))
    # rawSpectrum: m incrementing u16 values
    parts.append(struct.pack(f"<{m}H", *range(m)))
    return b"".join(parts)


def test_spectrum_frame_no_tm30_fields_at_correct_offsets():
    m = 711
    valid = _build_valid_data(m=m, include_tm30=False)
    # PROTOCOL.md says validData = 275 + 2M.
    assert len(valid) == 275 + 2 * m

    frame = decode_spectrum_frame(valid, include_tm30=False)
    assert frame.exposure_status == ExposureStatus.Normal
    assert frame.exposure_time_us == 2500
    assert frame.photometric.X == pytest.approx(1.0)
    assert frame.photometric.CCT == pytest.approx(5000.0)
    assert frame.photometric.Ra == pytest.approx(95.0)
    assert frame.photometric.lux == pytest.approx(120.0)
    assert frame.blue_hazard.Eb == pytest.approx(0.7)
    assert frame.nir.redEe == pytest.approx(1.1)
    assert frame.nir.nirEeA == pytest.approx(2.2)
    assert frame.nir.nirEeB == pytest.approx(3.3)
    assert frame.plant.PAR == pytest.approx(42.0)
    assert frame.plant.PPFD == pytest.approx(800.0)
    assert frame.spectrum_coefficient == 2
    assert len(frame.raw_spectrum) == m
    assert frame.raw_spectrum[0] == 0
    assert frame.raw_spectrum[m - 1] == m - 1
    assert frame.tm30 is None


def test_actual_spectrum_applies_coefficient():
    valid = _build_valid_data(m=3, coefficient=2)
    frame = decode_spectrum_frame(valid, include_tm30=False)
    assert frame.actual_spectrum == [0.0, 0.01, 0.02]


def test_actual_spectrum_with_negative_coefficient():
    valid = _build_valid_data(m=3, coefficient=-1)
    frame = decode_spectrum_frame(valid, include_tm30=False)
    # divisor = 10**-1 = 0.1, so raw/0.1 = raw*10
    assert frame.actual_spectrum == [0.0, 10.0, 20.0]


def test_spectrum_frame_with_tm30_fields_at_correct_offsets():
    m = 711
    valid = _build_valid_data(m=m, include_tm30=True)
    # validData = 2731 + 2M
    assert len(valid) == 2731 + 2 * m

    frame = decode_spectrum_frame(valid, include_tm30=True)
    assert frame.tm30 is not None
    tm30 = frame.tm30
    assert len(tm30.referenceSpectrum) == 401
    assert tm30.referenceSpectrum[0] == pytest.approx(11.0)
    assert tm30.referenceSpectrum[400] == pytest.approx(12.0)
    assert len(tm30.Eab) == 99
    assert tm30.Eab[0] == pytest.approx(13.0)
    assert tm30.Eab[98] == pytest.approx(14.0)
    assert tm30.Rf == pytest.approx(90.0)
    assert tm30.Rg == pytest.approx(105.0)
    assert len(tm30.chromaShift) == 16
    assert tm30.chromaShift[0] == pytest.approx(1.5)
    assert tm30.chromaShift[15] == pytest.approx(2.5)
    assert len(tm30.hueShift) == 16
    assert len(tm30.colorFidelity) == 16
    assert len(tm30.cesAbTest) == 16
    assert tm30.cesAbTest[0] == pytest.approx((0.11, 0.22))
    assert len(tm30.cesAbReference) == 16
    assert tm30.cesAbReference[15] == pytest.approx((7.7, 8.8))

    # The non-TM30 fields must still be in their original offsets.
    assert frame.photometric.CCT == pytest.approx(5000.0)
    assert frame.spectrum_coefficient == 2
    assert len(frame.raw_spectrum) == m


def test_spectrum_frame_totallen_matches_doc_example():
    """PROTOCOL.md §4.1: M=711 -> totalLen = 1706 = 0xAA 0x06 0x00."""
    valid = _build_valid_data(m=711, include_tm30=False)
    frame = build_response_frame(Cmd.CAPTURE_SINGLE_NO_TM30, valid)
    assert len(frame) == 1706
    assert frame[2:5] == bytes.fromhex("AA 06 00".replace(" ", ""))

    # Roundtrip parse + decode should succeed.
    _, parsed = parse_frame(frame, expected_cmd_type=Cmd.CAPTURE_SINGLE_NO_TM30)
    decoded = decode_spectrum_frame(parsed, include_tm30=False)
    assert decoded.exposure_time_us == 2500


def test_spectrum_frame_tm30_totallen_matches_doc_example():
    """PROTOCOL.md §4.2: with TM30, M=711 -> totalLen = 4162 = 0x42 0x10 0x00."""
    valid = _build_valid_data(m=711, include_tm30=True)
    frame = build_response_frame(Cmd.CAPTURE_SINGLE_WITH_TM30, valid)
    assert len(frame) == 4162
    assert frame[2:5] == bytes.fromhex("42 10 00".replace(" ", ""))


def test_spectrum_frame_too_short_raises():
    with pytest.raises(Exception):
        decode_spectrum_frame(b"\x00" * 10, include_tm30=False)


def test_spectrum_frame_odd_raw_length_raises():
    valid = _build_valid_data(m=2)
    # Chop one byte off the end so spectrum block is odd.
    with pytest.raises(Exception):
        decode_spectrum_frame(valid[:-1], include_tm30=False)
