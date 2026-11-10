"""Verwaltung benannter CAN-Verbindungen (Multi-Kanal)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..config.schema import ConnectionSpec
from ..core.errors import ConflictError, NotConnectedError
from .channel import CanChannel

log = logging.getLogger("udsbench.app.can")


class ConnectionManager:
    def __init__(self) -> None:
        self.channels: dict[str, CanChannel] = {}
        self.specs: dict[str, ConnectionSpec] = {}
        self.global_listeners: list[Callable[[Any], None]] = []
        self.on_change: list[Callable[[str, str], Any]] = []

    def get(self, name: str) -> CanChannel:
        ch = self.channels.get(name)
        if ch is None or not ch.is_open:
            raise NotConnectedError(f"Kanal {name!r} ist nicht verbunden")
        return ch

    async def connect(self, spec: ConnectionSpec) -> CanChannel:
        if spec.name in self.channels and self.channels[spec.name].is_open:
            raise ConflictError(f"Kanal {spec.name!r} ist bereits verbunden")
        ch = CanChannel(spec.name, spec.backend, spec.options)
        for fn in self.global_listeners:
            ch.add_listener(fn)
        await ch.open()
        self.channels[spec.name] = ch
        self.specs[spec.name] = spec
        log.info("Kanal %s verbunden (%s %s)", spec.name, spec.backend, ch.adapter.status().get("options"))
        for cb in self.on_change:
            await _maybe_await(cb(spec.name, "connected"))
        return ch

    async def disconnect(self, name: str) -> None:
        ch = self.channels.pop(name, None)
        self.specs.pop(name, None)
        if ch is None:
            raise NotConnectedError(f"Kanal {name!r} ist nicht verbunden")
        for cb in self.on_change:
            await _maybe_await(cb(name, "disconnecting"))
        await ch.close()
        log.info("Kanal %s getrennt", name)
        for cb in self.on_change:
            await _maybe_await(cb(name, "disconnected"))

    async def disconnect_all(self) -> None:
        for name in list(self.channels):
            try:
                await self.disconnect(name)
            except Exception:  # pragma: no cover
                log.exception("Trennen von %s fehlgeschlagen", name)

    async def reset(self, name: str) -> None:
        ch = self.get(name)
        await ch.reset()
        log.info("Kanal %s zurückgesetzt", name)

    def status(self) -> list[dict[str, Any]]:
        out = []
        for name, ch in self.channels.items():
            st = ch.status()
            spec = self.specs.get(name)
            st["simulate"] = bool(spec and spec.simulate)
            out.append(st)
        return out


async def _maybe_await(v: Any) -> None:
    import inspect

    if inspect.isawaitable(v):
        await v
