"""Public data types for the H1 SDK.

All dataclasses mirror the byte layout documented in PROTOCOL.md §4/§5.
Field order MUST match the protocol for ``protocol.py`` to decode correctly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExposureMode(IntEnum):
    Manual = 0x00
    Auto = 0x01


class WorkingMode(IntEnum):
    Streaming = 0x00
    Trigger = 0x01


class CieMode(IntEnum):
    Cie1931_2 = 0x00
    Cie1964_10 = 0x01
    Cie2015_2 = 0x02
    Cie2015_10 = 0x03


class ExposureStatus(IntEnum):
    Normal = 0x00
    Over = 0x01
    Under = 0x02


# ---------------------------------------------------------------------------
# Device meta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceInfo:
    serial_number: str


@dataclass(frozen=True)
class WavelengthRange:
    start: int
    end: int

    @property
    def count(self) -> int:
        """Number of wavelength points = end - start + 1."""
        return self.end - self.start + 1


# ---------------------------------------------------------------------------
# Spectrum sub-structures
# ---------------------------------------------------------------------------


@dataclass
class PhotometricParams:
    """47 floats, see PROTOCOL.md §5.1 for field semantics."""

    X: float = 0.0
    Y: float = 0.0
    Z: float = 0.0
    x: float = 0.0
    y: float = 0.0
    uk: float = 0.0
    vk: float = 0.0
    u_prime: float = 0.0
    v_prime: float = 0.0
    CCT: float = 0.0
    Nit: float = 0.0
    r_ratio: float = 0.0
    g_ratio: float = 0.0
    b_ratio: float = 0.0
    DUV: float = 0.0
    Ra: float = 0.0
    R1: float = 0.0
    R2: float = 0.0
    R3: float = 0.0
    R4: float = 0.0
    R5: float = 0.0
    R6: float = 0.0
    R7: float = 0.0
    R8: float = 0.0
    R9: float = 0.0
    R10: float = 0.0
    R11: float = 0.0
    R12: float = 0.0
    R13: float = 0.0
    R14: float = 0.0
    R15: float = 0.0
    Lp: float = 0.0
    HW: float = 0.0
    Ld: float = 0.0
    purity: float = 0.0
    SP: float = 0.0
    SDCM_k: float = 0.0
    k: float = 0.0
    lux: float = 0.0
    Ee: float = 0.0
    fc: float = 0.0
    CQS: float = 0.0
    GAI_EES: float = 0.0
    GAI_BB_8: float = 0.0
    GAI_BB_15: float = 0.0
    EML: float = 0.0
    M_EDI: float = 0.0


# Number of float fields in PhotometricParams (must equal 47, asserted at import).
PHOTOMETRIC_FIELD_COUNT = len(PhotometricParams.__dataclass_fields__)
assert PHOTOMETRIC_FIELD_COUNT == 47, "PhotometricParams must have 47 fields"


@dataclass
class BlueHazardParams:
    """1 float — see PROTOCOL.md §5.2."""

    Eb: float = 0.0


@dataclass
class NirParams:
    """3 floats — see PROTOCOL.md §5.3."""

    redEe: float = 0.0
    nirEeA: float = 0.0
    nirEeB: float = 0.0


@dataclass
class PlantParams:
    """16 floats — see PROTOCOL.md §5.4."""

    PAR: float = 0.0
    Eca: float = 0.0
    Ecb: float = 0.0
    Eb: float = 0.0
    Ey: float = 0.0
    Er: float = 0.0
    Erb_ratio: float = 0.0
    PPFD: float = 0.0
    PPFDb: float = 0.0
    PPFDy: float = 0.0
    PPFDr: float = 0.0
    PPFDfr: float = 0.0
    PPFDr_ratio: float = 0.0
    PPFDy_ratio: float = 0.0
    PPFDb_ratio: float = 0.0
    YPFD: float = 0.0


PLANT_FIELD_COUNT = len(PlantParams.__dataclass_fields__)
assert PLANT_FIELD_COUNT == 16, "PlantParams must have 16 fields"


@dataclass
class Tm30Params:
    """614 floats — see PROTOCOL.md §5.5 for offsets.

    Total = 401 + 99 + 1 + 1 + 16 + 16 + 16 + 32 + 32 = 614.
    """

    referenceSpectrum: List[float] = field(default_factory=list)  # length 401
    Eab: List[float] = field(default_factory=list)                # length 99
    Rf: float = 0.0
    Rg: float = 0.0
    chromaShift: List[float] = field(default_factory=list)        # length 16
    hueShift: List[float] = field(default_factory=list)           # length 16
    colorFidelity: List[float] = field(default_factory=list)      # length 16
    cesAbTest: List[Tuple[float, float]] = field(default_factory=list)       # 16 pairs
    cesAbReference: List[Tuple[float, float]] = field(default_factory=list)  # 16 pairs


# ---------------------------------------------------------------------------
# Top-level frame
# ---------------------------------------------------------------------------


@dataclass
class SpectrumFrame:
    """One spectral measurement, with optional TM30 block.

    See PROTOCOL.md §4 for byte layout.
    ``raw_spectrum`` is the un-scaled u16 array; ``actual_spectrum`` applies the
    coefficient on demand.
    """

    exposure_status: ExposureStatus
    exposure_time_us: int
    photometric: PhotometricParams
    blue_hazard: BlueHazardParams
    nir: NirParams
    plant: PlantParams
    spectrum_coefficient: int
    raw_spectrum: List[int]
    tm30: Optional[Tm30Params] = None

    @property
    def actual_spectrum(self) -> List[float]:
        """raw_spectrum[i] / (10 ** spectrum_coefficient)."""
        divisor = 10.0 ** self.spectrum_coefficient
        return [v / divisor for v in self.raw_spectrum]
