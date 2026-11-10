"""Startet/stoppt ECU-Testdoubles für virtuelle Kanäle."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ..core.errors import NotFoundError
from ..security.providers import SeedKeyProvider
from .ecu import SimulatedEcu

if TYPE_CHECKING:
    from ..core.platform import Platform

log = logging.getLogger("udsbench.app.sim")


class SimulationManager:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.ecus: dict[str, SimulatedEcu] = {}
        self._lock = asyncio.Lock()

    def _provider(self, ref: str, params: dict[str, Any]) -> SeedKeyProvider:
        return self.platform.security.provider(ref)

    async def start_for_channel(self, channel: str) -> list[str]:
        async with self._lock:
            return await self._start_for_channel(channel)

    async def _start_for_channel(self, channel: str) -> list[str]:
        spec = self.platform.connections.specs.get(channel)
        if spec is None or spec.backend != "virtual":
            return []
        bus = str(spec.options.get("bus", spec.options.get("channel", "vbus0")))
        merged = self.platform.packages.merged
        started = []
        for cfg in merged.simulation:
            if not cfg.enabled or cfg.ecu in self.ecus:
                continue
            rdef = merged.ecus.get(cfg.ecu)
            if rdef is None or rdef.profile.channel != channel:
                continue
            sim = SimulatedEcu(cfg, rdef.profile, bus, self._provider)
            sim.channel_name = channel
            await sim.start()
            self.ecus[cfg.ecu] = sim
            started.append(cfg.ecu)
        if started:
            self.platform.events.publish("simulation", state="started", ecus=started, channel=channel)
        return started

    async def stop_for_channel(self, channel: str) -> None:
        async with self._lock:
            merged = self.platform.packages.merged
            for ecu_id in list(self.ecus):
                rdef = merged.ecus.get(ecu_id)
                sim = self.ecus.get(ecu_id)
                if sim is not None and (
                    rdef is None or rdef.profile.channel == channel or sim.channel_name == channel
                ):
                    self.ecus.pop(ecu_id, None)
                    await sim.stop()

    async def _stop_all(self) -> None:
        for ecu_id in list(self.ecus):
            sim = self.ecus.pop(ecu_id, None)
            if sim is not None:
                await sim.stop()

    async def stop_all(self) -> None:
        async with self._lock:
            await self._stop_all()

    async def restart(self) -> list[str]:
        async with self._lock:
            await self._stop_all()
            started: list[str] = []
            for name, spec in list(self.platform.connections.specs.items()):
                if spec.simulate:
                    started += await self._start_for_channel(name)
            return started

    def get(self, ecu_id: str) -> SimulatedEcu:
        if ecu_id not in self.ecus:
            raise NotFoundError(f"Kein Testdouble für ECU {ecu_id!r} aktiv")
        return self.ecus[ecu_id]

    def status(self) -> list[dict[str, Any]]:
        return [sim.state() for sim in self.ecus.values()]
