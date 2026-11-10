"""Logischer CAN-Kanal: kapselt einen Adapter, verteilt Frames an Listener, führt Statistik."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from ..core.errors import NotConnectedError, TransportError
from .adapters import CanAdapter, create_adapter
from .frame import CanFrame

log = logging.getLogger("udsbench.app.can")
frame_log = logging.getLogger("udsbench.comm.can")
TRACE = 5

Listener = Callable[[CanFrame], None]


class CanChannel:
    def __init__(self, name: str, backend: str, options: dict[str, Any]) -> None:
        self.name = name
        self.backend = backend
        self.options = dict(options)
        self.adapter: CanAdapter = create_adapter(backend, name, options)
        self._listeners: list[Listener] = []
        self.tx_count = 0
        self.rx_count = 0
        self.tx_errors = 0
        self.connected_at: float | None = None
        self._send_lock = asyncio.Lock()

    # Listener ---------------------------------------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _dispatch(self, frame: CanFrame) -> None:
        frame.channel = self.name
        if frame.direction == "rx":
            self.rx_count += 1
        if frame_log.isEnabledFor(TRACE):
            frame_log.log(
                TRACE,
                "%s %s %s [%d] %s",
                self.name,
                frame.direction.upper(),
                frame.id_str(),
                len(frame.data),
                frame.data.hex(" ").upper(),
            )
        for fn in list(self._listeners):
            try:
                fn(frame)
            except Exception:  # pragma: no cover - Listenerfehler dürfen den Bus nicht stoppen
                log.exception("Fehler in CAN-Listener")

    # Lebenszyklus -----------------------------------------------------------------------
    async def open(self) -> None:
        await self.adapter.open(self._dispatch)
        self.connected_at = time.time()

    async def close(self) -> None:
        await self.adapter.close()
        self.connected_at = None

    async def reset(self) -> None:
        await self.adapter.close()
        await self.adapter.open(self._dispatch)
        self.tx_errors = 0

    @property
    def is_open(self) -> bool:
        return self.adapter.is_open

    async def send(self, frame: CanFrame, timeout: float | None = None) -> CanFrame:
        if not self.is_open:
            raise NotConnectedError(f"Kanal {self.name!r} ist nicht verbunden")
        frame.channel = self.name
        frame.direction = "tx"
        async with self._send_lock:
            try:
                if timeout:
                    await asyncio.wait_for(self.adapter.send(frame), timeout)
                else:
                    await self.adapter.send(frame)
            except TimeoutError as exc:
                self.tx_errors += 1
                raise TransportError(f"N_As/N_Ar-Timeout beim Senden auf {self.name}") from exc
            except Exception:
                self.tx_errors += 1
                raise
            frame.timestamp = time.time()
            self.tx_count += 1
        self._dispatch(frame)
        return frame

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "backend": self.backend,
            "connected": self.is_open,
            "connected_at": self.connected_at,
            "tx": self.tx_count,
            "rx": self.rx_count,
            "tx_errors": self.tx_errors,
            "adapter": self.adapter.status(),
        }


def _masked_frame_data(data: bytes) -> str:
    """Hex-Darstellung für das TRACE-Log; SecurityAccess-Inhalte (0x27/0x67) werden bei aktiver Maskierung verborgen."""
    from ..logs.setup import get_masker

    h = data.hex(" ").upper()
    if not get_masker().enabled:
        return h
    for off in (1, 2, 3):  # SID-Position bei SF/FF, normale bzw. extended/mixed Adressierung
        if off < len(data) and data[off] in (0x27, 0x67) and (data[off - 1] >> 4) in (0, 1):
            return data[: off + 2].hex(" ").upper() + " ***"
    return h
