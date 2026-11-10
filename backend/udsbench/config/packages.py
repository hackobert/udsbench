"""Verwaltung der Konfig-Pakete: Laden, Aktivieren, Zusammenführen, Kollisionsprüfung."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..catalogs.models import DidDef, DtcDef, RoutineDef
from ..catalogs.view import CatalogView
from ..core.errors import ConflictError, NotFoundError, ValidationFailed
from ..isotp.profile import IsoTpProfile
from ..messages.models import MessageDef, SequenceDef
from ..simulation.models import SimEcuConfig
from ..testrunner.models import SuiteDef, TestDef
from .loader import dump_package, load_package_file, package_hash, parse_package, safe_name
from .schema import EcuDef, Package, SecurityProviderDef

log = logging.getLogger("udsbench.app.config")


@dataclass
class PackageEntry:
    package: Package
    source: str  # Dateipfad oder "api"
    hash: str
    builtin: bool = False
    error: str | None = None

    @property
    def id(self) -> str:
        return self.package.package.id

    def summary(self, active: bool) -> dict[str, Any]:
        p = self.package
        return {
            "id": p.package.id,
            "name": p.package.name,
            "version": p.package.version,
            "description": p.package.description,
            "source": self.source,
            "builtin": self.builtin,
            "hash": self.hash,
            "active": active,
            "counts": {
                "isotp_profiles": len(p.isotp_profiles),
                "ecus": len(p.ecus),
                "dids": len(p.catalogs.dids),
                "dtcs": len(p.catalogs.dtcs),
                "routines": len(p.catalogs.routines),
                "messages": len(p.messages),
                "sequences": len(p.sequences),
                "tests": len(p.tests),
                "testsuites": len(p.testsuites),
                "simulated_ecus": len(p.simulation.ecus),
            },
        }


@dataclass
class EcuRuntimeDef:
    """Aufgelöste ECU-Definition (ISO-TP-Profil eingesetzt)."""

    ecu: EcuDef
    profile: IsoTpProfile
    package: str


@dataclass
class MergedConfig:
    ecus: dict[str, EcuRuntimeDef] = field(default_factory=dict)
    profiles: dict[str, IsoTpProfile] = field(default_factory=dict)
    providers: dict[str, SecurityProviderDef] = field(default_factory=dict)
    catalogs: CatalogView = field(default_factory=CatalogView)
    messages: dict[str, MessageDef] = field(default_factory=dict)
    sequences: dict[str, SequenceDef] = field(default_factory=dict)
    tests: dict[str, TestDef] = field(default_factory=dict)
    testsuites: dict[str, SuiteDef] = field(default_factory=dict)
    simulation: list[SimEcuConfig] = field(default_factory=list)
    origin: dict[str, str] = field(default_factory=dict)  # "kind:id" → package


class PackageManager:
    def __init__(self, dirs: list[Path], user_dir: Path, state_file: Path) -> None:
        self.dirs = dirs
        self.user_dir = user_dir
        self.state_file = state_file
        self.entries: dict[str, PackageEntry] = {}
        self.invalid: list[dict[str, Any]] = []
        self.active: list[str] = []
        self.merged = MergedConfig()
        self.listeners: list[Any] = []

    # Laden ----------------------------------------------------------------------------------
    def scan(self) -> None:
        self.entries.clear()
        self.invalid.clear()
        seen: set[Path] = set()
        for d in [*self.dirs, self.user_dir]:
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if f in seen or f.suffix.lower() not in (".yaml", ".yml", ".json"):
                    continue
                seen.add(f)
                try:
                    pkg = load_package_file(f)
                except ValidationFailed as exc:
                    self.invalid.append({"file": str(f), "error": exc.message, "details": exc.details})
                    log.error("Paket %s ungültig: %s %s", f.name, exc.message, exc.details or "")
                    continue
                if pkg.package.id in self.entries:
                    self.invalid.append({"file": str(f), "error": f"Paket-ID {pkg.package.id!r} doppelt"})
                    continue
                self.entries[pkg.package.id] = PackageEntry(
                    pkg, str(f), package_hash(pkg), builtin=".example." in f.name
                )

    def load_state(self, override: list[str] | None) -> None:
        wanted: list[str] = []
        if override is not None:
            wanted = list(override)
        elif self.state_file.exists():
            try:
                wanted = json.loads(self.state_file.read_text()).get("active", [])
            except Exception:  # pragma: no cover
                wanted = []
        else:
            wanted = [pid for pid, e in self.entries.items() if e.builtin]
        wanted = [w for w in wanted if w in self.entries]
        try:
            self.set_active(wanted, persist=False)
        except ConflictError as exc:
            log.error("Aktive Pakete kollidieren: %s – starte ohne aktive Pakete", exc.message)
            self.set_active([], persist=False)

    def _persist(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps({"active": self.active}, indent=2))

    # Verwaltung -----------------------------------------------------------------------------
    def list_items(self) -> list[dict[str, Any]]:
        return [e.summary(pid in self.active) for pid, e in self.entries.items()]

    def get(self, pid: str) -> PackageEntry:
        if pid not in self.entries:
            raise NotFoundError(f"Paket {pid!r} nicht gefunden")
        return self.entries[pid]

    def add(self, data: Any, *, overwrite: bool = False, activate: bool = False) -> PackageEntry:
        pkg = parse_package(data)
        pid = safe_name(pkg.package.id)
        if pid in self.entries and not overwrite:
            raise ConflictError(f"Paket {pid!r} existiert bereits (overwrite=true zum Ersetzen)")
        if pid in self.entries and self.entries[pid].builtin:
            raise ConflictError(f"Beispielpaket {pid!r} kann nicht überschrieben werden")
        entry = PackageEntry(pkg, str(self.user_dir / f"{pid}.yaml"), package_hash(pkg))
        previous = self.entries.get(pid)
        self.entries[pid] = entry
        try:
            # erst Aktivierung/Kollisionen prüfen, dann speichern – bei Fehlern bleibt alles unverändert
            if pid in self.active:
                self.set_active(self.active)
            elif activate:
                self.set_active([*self.active, pid])
        except Exception:
            if previous is None:
                del self.entries[pid]
            else:
                self.entries[pid] = previous
            raise
        self.user_dir.mkdir(parents=True, exist_ok=True)
        Path(entry.source).write_text(dump_package(pkg), encoding="utf-8")
        return entry

    def delete(self, pid: str) -> None:
        e = self.get(pid)
        if e.builtin:
            raise ConflictError("Beispielpakete können nicht gelöscht werden")
        if pid in self.active:
            self.set_active([a for a in self.active if a != pid])
        p = Path(e.source)
        if p.exists() and p.parent == self.user_dir:
            p.unlink()
        del self.entries[pid]

    def activate(self, pid: str) -> None:
        self.get(pid)
        if pid not in self.active:
            self.set_active([*self.active, pid])

    def deactivate(self, pid: str) -> None:
        self.get(pid)
        self.set_active([a for a in self.active if a != pid])

    def set_active(self, ids: list[str], persist: bool = True) -> None:
        for pid in ids:
            self.get(pid)
        merged = self._merge(ids)
        self.active = list(ids)
        self.merged = merged
        if persist:
            self._persist()
        for fn in list(self.listeners):
            fn(self.merged)

    # Zusammenführen -------------------------------------------------------------------------
    def _merge(self, ids: list[str]) -> MergedConfig:
        m = MergedConfig()
        collisions: list[str] = []

        def put(kind: str, store: dict[Any, Any], key: Any, value: Any, pid: str) -> None:
            okey = f"{kind}:{key}"
            if okey in m.origin and m.origin[okey] != pid:
                collisions.append(f"{kind} {key!r} in {m.origin[okey]!r} und {pid!r}")
                return
            m.origin[okey] = pid
            store[key] = value

        for pid in ids:
            pkg = self.entries[pid].package
            for name, prof in pkg.isotp_profiles.items():
                put("isotp_profile", m.profiles, name, prof, pid)
            for prov in pkg.security_providers:
                put("security_provider", m.providers, prov.id, prov, pid)
            for ecu in pkg.ecus:
                prof = pkg.isotp_profiles[ecu.isotp] if isinstance(ecu.isotp, str) else ecu.isotp
                put("ecu", m.ecus, ecu.id, EcuRuntimeDef(ecu, prof, pid), pid)
            d: DidDef
            for d in pkg.catalogs.dids:
                put("did", m.catalogs.dids, d.id, d, pid)
            t: DtcDef
            for t in pkg.catalogs.dtcs:
                put("dtc", m.catalogs.dtcs, t.code, t, pid)
            r: RoutineDef
            for r in pkg.catalogs.routines:
                put("routine", m.catalogs.routines, r.id, r, pid)
            for msg in pkg.messages:
                put("message", m.messages, msg.id, msg, pid)
            for seq in pkg.sequences:
                put("sequence", m.sequences, seq.id, seq, pid)
            for tc in pkg.tests:
                put("test", m.tests, tc.id, tc, pid)
            for ts in pkg.testsuites:
                put("testsuite", m.testsuites, ts.id, ts, pid)
            m.simulation.extend(pkg.simulation.ecus)
        if collisions:
            raise ConflictError("Namenskollision zwischen aktiven Paketen", details=collisions)
        # Querverweise prüfen
        problems: list[str] = []
        for sim in m.simulation:
            if sim.ecu not in m.ecus:
                problems.append(f"Simulation verweist auf unbekannte ECU {sim.ecu!r}")
        for ecu_id, e in m.ecus.items():
            for lvl in e.ecu.security_levels:
                if lvl.provider and lvl.provider not in m.providers:
                    problems.append(f"ECU {ecu_id!r}: Security-Provider {lvl.provider!r} unbekannt")
        if problems:
            raise ConflictError("Ungültige Querverweise", details=problems)
        return m

    def active_hashes(self) -> list[dict[str, str]]:
        return [
            {"id": pid, "version": self.entries[pid].package.package.version, "hash": self.entries[pid].hash}
            for pid in self.active
        ]
