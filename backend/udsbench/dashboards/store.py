"""Dashboard-Speicher (Datenverzeichnis) + Dashboards aus aktiven Konfig-Paketen (schreibgeschützt)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.errors import ConflictError, NotFoundError
from .models import Dashboard

if TYPE_CHECKING:
    from ..core.platform import Platform

DEFAULT = {
    "id": "default",
    "name": "Übersicht",
    "description": "Standard-Dashboard (anpassbar)",
    "panels": [
        {"id": "status", "type": "ecu_status", "title": "ECUs", "x": 0, "y": 0, "w": 4, "h": 3},
        {
            "id": "chart",
            "type": "timechart",
            "title": "UDS-Antworten (5 min)",
            "x": 4,
            "y": 0,
            "w": 8,
            "h": 3,
            "config": {"metric": "uds", "group_by": "type", "window_s": 300},
        },
        {
            "id": "stats",
            "type": "stats",
            "title": "Statistik (15 min)",
            "x": 0,
            "y": 3,
            "w": 4,
            "h": 3,
            "config": {"window_s": 900},
        },
        {
            "id": "events",
            "type": "events",
            "title": "Ereignisse",
            "x": 4,
            "y": 3,
            "w": 8,
            "h": 3,
            "config": {"limit": 50},
        },
    ],
}


class DashboardStore:
    def __init__(self, platform: Platform, file: Path) -> None:
        self.platform = platform
        self.file = file
        self.items: dict[str, Dashboard] = {}
        self._load()

    def _load(self) -> None:
        if self.file.exists():
            data = json.loads(self.file.read_text(encoding="utf-8"))
            self.items = {d["id"]: Dashboard.model_validate(d) for d in data.get("dashboards", [])}
        if not self.items:
            self.items = {"default": Dashboard.model_validate(DEFAULT)}

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(
            json.dumps(
                {"dashboards": [d.model_dump(mode="json") for d in self.items.values()]},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    def package_dashboards(self) -> dict[str, tuple[Dashboard, str]]:
        out: dict[str, tuple[Dashboard, str]] = {}
        for pid in self.platform.packages.active:
            for d in self.platform.packages.entries[pid].package.dashboards:
                out[d.id] = (d, pid)
        return out

    def list_items(self) -> list[dict[str, Any]]:
        res = [{**d.model_dump(mode="json"), "source": "user", "editable": True} for d in self.items.values()]
        for did, (d, pid) in self.package_dashboards().items():
            if did not in self.items:
                res.append({**d.model_dump(mode="json"), "source": pid, "editable": False})
        return res

    def get(self, did: str) -> dict[str, Any]:
        for d in self.list_items():
            if d["id"] == did:
                return d
        raise NotFoundError(f"Dashboard {did!r} nicht gefunden")

    def put(self, d: Dashboard, *, create: bool) -> Dashboard:
        if create and (d.id in self.items or d.id in self.package_dashboards()):
            raise ConflictError(f"Dashboard {d.id!r} existiert bereits")
        if not create and d.id not in self.items and d.id in self.package_dashboards():
            raise ConflictError("Dashboard aus einem Konfig-Paket – bitte zuerst duplizieren")
        self.items[d.id] = d
        self._save()
        return d

    def delete(self, did: str) -> None:
        if did not in self.items:
            raise NotFoundError(f"Dashboard {did!r} nicht gefunden oder nicht löschbar")
        del self.items[did]
        self._save()
