"""Gemeinsame API-Abhängigkeiten: Plattformzugriff und Token-Authentifizierung."""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, WebSocket, status

from ..core.platform import Platform


def get_platform(request: Request) -> Platform:
    return request.app.state.platform  # type: ignore[no-any-return]


def _extract(headers: dict[str, str], query: dict[str, str]) -> str | None:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get("x-api-token") or query.get("token")


def check_token(expected: str | None, provided: str | None) -> bool:
    if not expected:
        return True
    return provided is not None and secrets.compare_digest(expected, provided)


async def require_auth(request: Request) -> None:
    expected = request.app.state.token
    if not check_token(
        expected, _extract({k.lower(): v for k, v in request.headers.items()}, dict(request.query_params))
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "API-Token fehlt oder ist ungültig",
            headers={"WWW-Authenticate": "Bearer"},
        )


def ws_authorized(ws: WebSocket) -> bool:
    expected = ws.app.state.token
    return check_token(
        expected, _extract({k.lower(): v for k, v in ws.headers.items()}, dict(ws.query_params))
    )


Auth = Depends(require_auth)
PlatformDep = Depends(get_platform)
