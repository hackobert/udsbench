"""Arbeitsbereich-Paket: per UI/API angelegte Botschaften, Sequenzen, Tests und Suiten."""

from __future__ import annotations

from typing import Any

from ..core.errors import ConflictError, NotFoundError
from .packages import PackageManager

WORKSPACE_ID = "workspace"
KINDS = {"messages": "messages", "sequences": "sequences", "tests": "tests", "testsuites": "testsuites"}


class Workspace:
    def __init__(self, packages: PackageManager) -> None:
        self.packages = packages

    def _data(self) -> dict[str, Any]:
        if WORKSPACE_ID in self.packages.entries:
            return self.packages.entries[WORKSPACE_ID].package.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        return {
            "schema_version": 1,
            "package": {
                "id": WORKSPACE_ID,
                "name": "Arbeitsbereich",
                "version": "0.0.1",
                "description": "Über UI/API angelegte Objekte",
            },
        }

    def upsert(self, kind: str, item: dict[str, Any], *, create: bool) -> dict[str, Any]:
        if kind not in KINDS:
            raise NotFoundError(f"Unbekannte Art {kind!r}")
        merged = self.packages.merged
        existing_origin = merged.origin.get(f"{kind[:-1]}:{item.get('id')}")
        if create and existing_origin is not None:
            raise ConflictError(
                f"{kind[:-1]} {item.get('id')!r} existiert bereits (Paket {existing_origin!r})"
            )
        if not create and existing_origin not in (None, WORKSPACE_ID):
            raise ConflictError(
                f"{item.get('id')!r} gehört zu Paket {existing_origin!r} und ist nur dort änderbar"
            )
        data = self._data()
        items = [x for x in data.get(KINDS[kind], []) if x.get("id") != item.get("id")]
        items.append(item)
        data[KINDS[kind]] = items
        activate = WORKSPACE_ID not in self.packages.active
        self.packages.add(data, overwrite=True, activate=activate)
        return item

    def delete(self, kind: str, item_id: str) -> None:
        origin = self.packages.merged.origin.get(f"{kind[:-1]}:{item_id}")
        if origin is None:
            raise NotFoundError(f"{item_id!r} nicht gefunden")
        if origin != WORKSPACE_ID:
            raise ConflictError(f"{item_id!r} gehört zu Paket {origin!r} und ist nur dort löschbar")
        data = self._data()
        data[KINDS[kind]] = [x for x in data.get(KINDS[kind], []) if x.get("id") != item_id]
        self.packages.add(data, overwrite=True)
