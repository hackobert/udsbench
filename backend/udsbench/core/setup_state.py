"""Einrichtungszustand: Assistent abgeschlossen? Gespeicherte Verbindungen für den nächsten Start.

Liegt als JSON im Datenverzeichnis (``data/setup.json``), damit die Einrichtung über die
Oberfläche ohne Bearbeiten von ``config/app.yaml`` dauerhaft wirkt. Verbindungen aus der
App-Konfiguration haben Vorrang.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config.schema import ConnectionSpec

log = logging.getLogger("udsbench.app.setup")

SETUP_FILE = "setup.json"


class SetupState:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / SETUP_FILE

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            log.warning("Einrichtungszustand %s nicht lesbar: %s", self.path, exc)
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def completed(self) -> bool:
        return bool(self.load().get("completed", False))

    def set_completed(self, value: bool) -> None:
        data = self.load()
        data["completed"] = value
        self._save(data)

    def connections(self) -> list[ConnectionSpec]:
        out = []
        for raw in self.load().get("connections", []) or []:
            try:
                out.append(ConnectionSpec.model_validate(raw))
            except ValueError as exc:
                log.warning("Gespeicherte Verbindung ungültig, wird ignoriert: %s", exc)
        return out

    def save_connections(self, specs: list[ConnectionSpec]) -> None:
        data = self.load()
        data["connections"] = [s.model_dump(mode="json") for s in specs]
        self._save(data)


def saved_connections(data_dir: Path) -> list[ConnectionSpec]:
    return SetupState(data_dir).connections()
