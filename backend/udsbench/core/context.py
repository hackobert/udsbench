"""Korrelations-IDs über contextvars (Request/Testlauf → Logs, Trace, Report)."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@contextlib.contextmanager
def correlated(cid: str | None = None) -> Iterator[str]:
    cid = cid or new_id()
    token = correlation_id.set(cid)
    try:
        yield cid
    finally:
        correlation_id.reset(token)


def current() -> str | None:
    return correlation_id.get()
