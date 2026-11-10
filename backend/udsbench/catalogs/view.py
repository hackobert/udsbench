"""Zusammengeführte Sicht auf alle Kataloge der aktiven Konfig-Pakete."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DidDef, DtcDef, RoutineDef


@dataclass
class CatalogView:
    dids: dict[int, DidDef] = field(default_factory=dict)
    dtcs: dict[int, DtcDef] = field(default_factory=dict)
    routines: dict[int, RoutineDef] = field(default_factory=dict)

    def did(self, did: int) -> DidDef | None:
        return self.dids.get(did)

    def find_did(self, ref: int | str) -> DidDef | None:
        if isinstance(ref, int):
            return self.dids.get(ref)
        for d in self.dids.values():
            if d.name == ref:
                return d
        try:
            from ..core.hexutil import parse_int

            return self.dids.get(parse_int(ref))
        except ValueError:
            return None

    def find_routine(self, ref: int | str) -> RoutineDef | None:
        if isinstance(ref, int):
            return self.routines.get(ref)
        for r in self.routines.values():
            if r.name == ref:
                return r
        try:
            from ..core.hexutil import parse_int

            return self.routines.get(parse_int(ref))
        except ValueError:
            return None


EMPTY = CatalogView()
