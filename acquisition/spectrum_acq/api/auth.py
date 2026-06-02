"""API authentication dependency (shared contract).

Provides ``require_token``, a FastAPI dependency that gates state-changing
and file-access routes behind a bearer token.

Backward-compatible by design: if the environment variable
``ACQUISITION_API_TOKEN`` is unset or empty, the dependency allows every
request (the current default behaviour). When the variable is set, a request
must present a matching token via either the ``Authorization: Bearer <token>``
header or the ``X-API-Token: <token>`` header, otherwise the dependency
raises ``HTTPException(status_code=401)``.

Dependency-light: stdlib + fastapi only. Use as ``Depends(require_token)``.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

_TOKEN_ENV_VAR = "ACQUISITION_API_TOKEN"


def _expected_token() -> str:
    """Return the configured API token, or "" if auth is disabled.

    Read from the environment on each request so the service can be
    reconfigured (e.g. via systemd unit changes + restart) without code
    edits, and so tests can toggle it with monkeypatch/setenv.
    """
    return (os.environ.get(_TOKEN_ENV_VAR) or "").strip()


def _extract_presented_token(authorization: str | None, x_api_token: str | None) -> str | None:
    """Pull the caller's token from the Authorization or X-API-Token header.

    Prefers the ``Authorization: Bearer <token>`` form; falls back to the
    raw ``X-API-Token`` header value. Returns None if neither yields a token.
    """
    if authorization:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            return credentials.strip()
    if x_api_token:
        return x_api_token.strip()
    return None


def require_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    """FastAPI dependency enforcing the API token when one is configured.

    No-op (allows the request) when ``ACQUISITION_API_TOKEN`` is unset/empty.
    Otherwise requires a matching ``Authorization: Bearer <token>`` or
    ``X-API-Token: <token>`` header and raises ``HTTPException(401)`` if the
    token is missing or incorrect.
    """
    expected = _expected_token()
    if not expected:
        # Auth disabled: backward-compatible default, allow everything.
        return

    presented = _extract_presented_token(authorization, x_api_token)
    # Constant-time comparison avoids leaking token length/prefix via timing.
    if presented is None or not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
