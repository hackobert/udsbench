"""Zentrale Zusammensetzung aller Dienste (eine Instanz je Serverprozess)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .. import __version__
from ..can.manager import ConnectionManager
from ..config.loader import resolve
from ..config.packages import MergedConfig, PackageManager
from ..config.schema import AppConfig, ConnectionSpec
from ..dashboards.store import DashboardStore
from ..logs.recorder import RecorderService
from ..logs.setup import get_buffer, setup_logging
from ..plugins.registry import registry
from ..reports.service import ReportService
from ..security.service import SecurityService
from ..simulation.manager import SimulationManager
from ..testrunner.runner import TestRunner
from .diag import DiagnosticsManager
from .events import EventBus
from .history import HistoryStore
from .setup_state import SetupState
from .trace import TraceService

log = logging.getLogger("udsbench.app")


def bundled_packages_dir() -> Path | None:
    here = Path(__file__).resolve().parent.parent
    for cand in (
        here / "_bundled" / "packages",  # installiertes Paket (Wheel)
        here.parent.parent / "config" / "packages",
    ):  # Start aus dem Quellbaum
        if cand.is_dir() and any(cand.glob("*.example.*")):
            return cand
    return None


class Platform:
    def __init__(self, config: AppConfig, base_dir: Path, *, configure_logging: bool = True) -> None:
        self.config = config
        self.base_dir = base_dir
        self.started = time.time()
        p = config.paths
        self.data_dir = resolve(base_dir, p.data_dir)
        self.log_dir = resolve(base_dir, config.logging.dir)
        if configure_logging:
            lc = config.logging
            setup_logging(
                lc.level,
                self.log_dir,
                console=lc.console,
                json_files=lc.json_files,
                max_bytes=lc.max_bytes,
                backups=lc.backups,
                buffer_size=lc.buffer_size,
                mask_secrets=lc.mask_secrets,
                mask_fields=lc.mask_fields,
            )
        pkg_dirs = [resolve(base_dir, d) for d in p.package_dirs]
        bundled = bundled_packages_dir()
        if bundled and not any(d.is_dir() and any(d.glob("*.example.*")) for d in pkg_dirs):
            pkg_dirs.append(bundled)
        self.events = EventBus()
        self.history = HistoryStore(self.data_dir / "history")
        self.events.sinks.append(self.history.sink)
        self.packages = PackageManager(pkg_dirs, self.data_dir / "packages", self.data_dir / "state.json")
        self.connections = ConnectionManager()
        self.trace = TraceService(self, config.trace.buffer_size)
        self.connections.global_listeners.append(self.trace.on_frame)
        self.diag = DiagnosticsManager(self)
        self.security = SecurityService(self, resolve(base_dir, p.providers_dir))
        self.security.mask = config.logging.mask_secrets
        self.sim = SimulationManager(self)
        self.recorder = RecorderService(self, resolve(base_dir, p.recordings_dir))
        self.runner = TestRunner(self, resolve(base_dir, p.reports_dir))
        self.reports = ReportService(self, resolve(base_dir, p.reports_dir))
        self.dashboards = DashboardStore(self, self.data_dir / "dashboards.json")
        self.setup = SetupState(self.data_dir)
        self.plugins_dir = resolve(base_dir, p.plugins_dir)
        self.connections.on_change.append(self._on_connection_change)
        self.packages.listeners.append(self._on_packages_changed)
        self._log_forward: Any = None
        self._sim_task: asyncio.Task[Any] | None = None
        self._sim_sig = ""

    # Lebenszyklus ---------------------------------------------------------------------------
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._log_forward = lambda d: loop.call_soon_threadsafe(lambda: self.events.publish("log", entry=d))
        get_buffer().subscribers.append(self._log_forward)
        registry.load_dir(self.plugins_dir)
        self.packages.scan()
        self.packages.load_state(self.config.active_packages)
        log.info(
            "udsbench %s gestartet – aktive Pakete: %s",
            __version__,
            ", ".join(self.packages.active) or "keine",
        )
        # Verbindungen aus der App-Konfiguration haben Vorrang vor den im Assistenten gespeicherten
        for spec in self.config.connections or self.setup.connections():
            try:
                await self.connect(spec)
            except Exception as exc:
                log.error("Automatische Verbindung %s fehlgeschlagen: %s", spec.name, exc)

    async def stop(self) -> None:
        for run in list(self.runner.runs.values()):
            if run.task and not run.task.done():
                run.cancel.set()
        for info in self.recorder.replays.values():
            t = info.get("_task")
            if t and not t.done():
                t.cancel()
        if self.recorder.active:
            self.recorder.stop()
        self.diag.close_all()
        await self.sim.stop_all()
        await self.connections.disconnect_all()
        self.history.close()
        if self._log_forward in get_buffer().subscribers:
            get_buffer().subscribers.remove(self._log_forward)

    # Verbindungen ---------------------------------------------------------------------------
    async def connect(self, spec: ConnectionSpec, *, replace: bool = False) -> dict[str, Any]:
        await self.connections.connect(spec, replace=replace)
        return self.connections.channels[spec.name].status()

    async def _on_connection_change(self, name: str, state: str) -> None:
        if state == "connected":
            spec = self.connections.specs.get(name)
            if spec and spec.simulate:
                await self.sim.start_for_channel(name)
            self.diag.rebuild()
        elif state == "disconnecting":
            await self.sim.stop_for_channel(name)
        elif state == "disconnected":
            self.diag.rebuild()
        self.events.publish("connection", channel=name, state=state, status=self.connections.status())

    def _on_packages_changed(self, merged: MergedConfig) -> None:
        self.trace.update_endpoints()
        self.security.invalidate()
        self.diag.rebuild()
        self.events.publish("packages", active=self.packages.active)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        # Testdouble nur neu starten, wenn sich Simulation oder ECU-Adressierung geändert hat
        sig = repr([c.model_dump() for c in merged.simulation]) + repr(
            sorted((k, v.profile.model_dump_json()) for k, v in merged.ecus.items())
        )
        if sig != self._sim_sig and any(s.simulate for s in self.connections.specs.values()):
            self._sim_task = loop.create_task(self.sim.restart())
        self._sim_sig = sig

    async def settle(self) -> None:
        """Wartet, bis durch Paketänderungen ausgelöste Neustarts (Testdouble) abgeschlossen sind."""
        task = self._sim_task
        if task is not None and not task.done():
            await task
        self.diag.rebuild()

    def info(self) -> dict[str, Any]:
        return {
            "name": "udsbench",
            "version": __version__,
            "uptime_s": round(time.time() - self.started, 1),
            "active_packages": self.packages.active,
            "connections": self.connections.status(),
            "simulation": [s["ecu"] for s in self.sim.status()],
            "recording": self.recorder.active.id if self.recorder.active else None,
            "language": self.config.language,
        }
