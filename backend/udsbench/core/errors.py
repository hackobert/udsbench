"""Fehlerhierarchie mit API-tauglichen Fehlercodes."""

from __future__ import annotations

from typing import Any


class UdsBenchError(Exception):
    code = "error"
    http_status = 400

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            d["details"] = self.details
        return d


class NotFoundError(UdsBenchError):
    code = "not_found"
    http_status = 404


class ConflictError(UdsBenchError):
    code = "conflict"
    http_status = 409


class ValidationFailed(UdsBenchError):
    code = "validation_error"
    http_status = 422


class NotConnectedError(UdsBenchError):
    code = "not_connected"
    http_status = 409


class TransportError(UdsBenchError):
    code = "transport_error"
    http_status = 502


class TimeoutError_(UdsBenchError):
    code = "timeout"
    http_status = 504


class ProviderError(UdsBenchError):
    code = "provider_error"
    http_status = 500
