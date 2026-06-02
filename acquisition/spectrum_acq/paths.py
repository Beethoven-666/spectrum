"""Filesystem path safety helpers (shared contract).

These helpers guard against path-traversal and injection of unexpected
characters in user-supplied names (e.g. sample names used as directory
names). They are intentionally dependency-light (stdlib only) so they can
be imported anywhere in the service without pulling in FastAPI.
"""

from __future__ import annotations

import pathlib
import re

# A name is valid iff it is 1-128 chars from a conservative whitelist of
# letters, digits, dot, underscore and hyphen. This forbids path separators
# ("/", "\\"), NUL bytes, whitespace and any other shell/FS metacharacters.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def valid_name(name: str) -> bool:
    """Return True iff *name* is a safe single path component.

    A valid name matches ``^[A-Za-z0-9._-]{1,128}$`` and is neither the
    current-directory (".") nor parent-directory ("..") reference. Any
    non-str input, or a name containing a path separator or disallowed
    character, returns False.
    """
    if not isinstance(name, str):
        return False
    if name in (".", ".."):
        return False
    return _NAME_RE.match(name) is not None


def safe_join(base: pathlib.Path, name: str) -> pathlib.Path:
    """Safely join *name* under *base*, returning the resolved child path.

    Raises ``ValueError`` unless both:
      * ``valid_name(name)`` is True, and
      * the resolved ``base / name`` lies inside the resolved ``base``.

    This defends against path traversal (e.g. ``..`` segments) and symlink
    escapes. The returned path is fully resolved (absolute, symlinks
    collapsed).
    """
    if not valid_name(name):
        raise ValueError(f"invalid name: {name!r}")

    base_resolved = pathlib.Path(base).resolve()
    child_resolved = (base_resolved / name).resolve()

    # Confirm the resolved child is contained within the resolved base.
    # is_relative_to (Python 3.9+) treats base itself as not "inside" base,
    # which is the behaviour we want: a bare name must produce a strict child.
    if child_resolved == base_resolved or not child_resolved.is_relative_to(base_resolved):
        raise ValueError(f"path escapes base directory: {name!r}")

    return child_resolved
