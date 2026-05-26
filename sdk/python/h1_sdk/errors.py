"""Exception hierarchy for the H1 SDK."""

from __future__ import annotations

from typing import Optional


class H1Error(Exception):
    """Base class for all H1 SDK errors."""


class ProtocolError(H1Error):
    """Raised when a frame is malformed (bad header/footer/length/checksum/dataType)."""


class H1TimeoutError(H1Error):
    """Raised when a serial read times out.

    Named with the H1 prefix to avoid shadowing the built-in ``TimeoutError``.
    """


class DeviceError(H1Error):
    """Raised when the device returns a non-success status code.

    Attributes:
        code:     The status byte returned by the device (e.g. ``0x15``, ``0xFF``).
        cmd_type: The command type that triggered the error, if known.
    """

    def __init__(
        self,
        code: int,
        message: str,
        cmd_type: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.cmd_type = cmd_type

    def __str__(self) -> str:
        cmd = f" (cmd=0x{self.cmd_type:02X})" if self.cmd_type is not None else ""
        return f"{super().__str__()} [code=0x{self.code:02X}{cmd}]"
