"""Einrichtung: eigene Geräte (ECUs) verwalten, Demo ein-/ausschalten, Verbindung für den Start speichern.

Eigene Geräte landen im Arbeitsbereich-Paket (``workspace``) mit eingebettetem ISO-TP-Profil.
Geräte aus anderen Paketen (z. B. der Demo) sind nur lesbar; die Demo lässt sich als Ganzes
ausblenden, indem die eingebauten Beispielpakete deaktiviert werden.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel

from ..config.schema import ConnectionSpec, EcuDef
from ..config.workspace import WORKSPACE_ID, Workspace
from ..core.errors import ConflictError, NotFoundError
from ..core.platform import Platform
from .deps import Auth, PlatformDep

router = APIRouter(prefix="/api/v1", dependencies=[Auth])


def _ok(**kw: Any) -> dict[str, Any]:
    return {"ok": True, **kw}


def _builtin_ids(p: Platform) -> list[str]:
    return [pid for pid, e in p.packages.entries.items() if e.builtin]


def _device(p: Platform, ecu_id: str) -> dict[str, Any]:
    merged = p.packages.merged
    rdef = merged.ecus.get(ecu_id)
    if rdef is None:
        raise NotFoundError(f"Gerät {ecu_id!r} nicht gefunden")
    entry = p.packages.entries.get(rdef.package)
    return {
        "id": ecu_id,
        "name": rdef.ecu.name,
        "description": rdef.ecu.description,
        "package": rdef.package,
        "editable": rdef.package == WORKSPACE_ID,
        "demo": bool(entry and entry.builtin),
        "connected": ecu_id in p.diag.runtimes,
        "profile": rdef.profile.model_dump(mode="json"),
        "definition": rdef.ecu.model_dump(mode="json", exclude_none=True),
    }


def _id_warnings(p: Platform, ecu: EcuDef) -> list[str]:
    """Hinweise auf CAN-ID-Überschneidungen mit anderen aktiven Geräten auf demselben Kanal."""
    if isinstance(ecu.isotp, str):
        prof = p.packages.merged.profiles.get(ecu.isotp)
        if prof is None:
            return []
    else:
        prof = ecu.isotp
    out = []
    for other_id, other in p.packages.merged.ecus.items():
        if other_id == ecu.id or other.profile.channel != prof.channel:
            continue
        o = other.profile
        same_ae = o.rx_address_extension == prof.rx_address_extension
        if o.rx_id == prof.rx_id and same_ae:
            out.append(
                f"Antwort-ID 0x{prof.rx_id:X} wird auch von {other_id!r} ({other.package}) verwendet – "
                "Antworten lassen sich dann nicht eindeutig zuordnen."
            )
        elif o.tx_id == prof.tx_id and o.tx_address_extension == prof.tx_address_extension:
            out.append(f"Anfrage-ID 0x{prof.tx_id:X} wird auch von {other_id!r} ({other.package}) verwendet.")
    return out


# =============================================================================================
# Geräte
# =============================================================================================


@router.get("/devices", tags=["devices"], summary="Alle Geräte mit Herkunft und Bearbeitbarkeit")
async def devices(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return [_device(p, ecu_id) for ecu_id in p.packages.merged.ecus]


@router.get("/devices/{ecu_id}", tags=["devices"])
async def device(ecu_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
    return _device(p, ecu_id)


def _save(p: Platform, item: dict[str, Any], *, create: bool) -> tuple[EcuDef, list[str]]:
    ecu = EcuDef.model_validate(item)
    if isinstance(ecu.isotp, str):
        raise ConflictError("Eigene Geräte brauchen ein eingebettetes ISO-TP-Profil (isotp als Objekt)")
    ecu.isotp.name = ecu.id
    Workspace(p.packages).upsert(
        "ecus", ecu.model_dump(mode="json", by_alias=True, exclude_none=True), create=create
    )
    return ecu, _id_warnings(p, ecu)


@router.post("/devices", tags=["devices"], summary="Eigenes Gerät anlegen")
async def create_device(item: dict[str, Any] = Body(...), p: Platform = PlatformDep) -> dict[str, Any]:
    ecu, warnings = _save(p, item, create=True)
    await p.settle()
    return _ok(device=_device(p, ecu.id), warnings=warnings)


@router.put("/devices/{ecu_id}", tags=["devices"], summary="Eigenes Gerät ändern")
async def update_device(
    ecu_id: str, item: dict[str, Any] = Body(...), p: Platform = PlatformDep
) -> dict[str, Any]:
    item["id"] = ecu_id
    ecu, warnings = _save(p, item, create=False)
    await p.settle()
    return _ok(device=_device(p, ecu.id), warnings=warnings)


@router.delete("/devices/{ecu_id}", tags=["devices"], summary="Eigenes Gerät löschen")
async def delete_device(ecu_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
    origin = p.packages.merged.origin.get(f"ecu:{ecu_id}")
    if origin is not None and origin != WORKSPACE_ID:
        entry = p.packages.entries.get(origin)
        if entry and entry.builtin:
            raise ConflictError(
                f"{ecu_id!r} ist ein Demo-Gerät. Demo-Geräte werden gemeinsam ausgeblendet: "
                'PUT /setup/demo mit {"enabled": false} oder in der Oberfläche *Geräte → Demo ausblenden*.'
            )
    Workspace(p.packages).delete("ecus", ecu_id)
    await p.settle()
    return _ok()


# =============================================================================================
# Einrichtung
# =============================================================================================


@router.get("/setup", tags=["setup"], summary="Einrichtungszustand (Assistent)")
async def setup_status(p: Platform = PlatformDep) -> dict[str, Any]:
    builtin = _builtin_ids(p)
    devs = [_device(p, e) for e in p.packages.merged.ecus]
    return {
        "completed": p.setup.completed,
        "demo": {
            "available": bool(builtin),
            "active": any(b in p.packages.active for b in builtin),
            "packages": builtin,
        },
        "devices": {"own": sum(d["editable"] for d in devs), "demo": sum(d["demo"] for d in devs)},
        "saved_connections": [s.model_dump(mode="json") for s in p.setup.connections()],
        "config_connections": [s.model_dump(mode="json") for s in p.config.connections],
    }


class DemoIn(BaseModel):
    enabled: bool


@router.put("/setup/demo", tags=["setup"], summary="Demo-Geräte (eingebaute Beispielpakete) ein-/ausblenden")
async def setup_demo(body: DemoIn, p: Platform = PlatformDep) -> dict[str, Any]:
    builtin = _builtin_ids(p)
    active = [a for a in p.packages.active if a not in builtin]
    if body.enabled:
        active = [*builtin, *active]
    p.packages.set_active(active)
    await p.settle()
    return _ok(active=p.packages.active)


@router.put("/setup/connections", tags=["setup"], summary="Verbindungen für den nächsten Start speichern")
async def setup_connections(
    specs: list[ConnectionSpec] = Body(...), p: Platform = PlatformDep
) -> dict[str, Any]:
    p.setup.save_connections(specs)
    return _ok(saved=[s.model_dump(mode="json") for s in specs])


class CompleteIn(BaseModel):
    completed: bool = True


@router.put("/setup/completed", tags=["setup"], summary="Assistent als erledigt markieren")
async def setup_completed(body: CompleteIn, p: Platform = PlatformDep) -> dict[str, Any]:
    p.setup.set_completed(body.completed)
    return _ok(completed=body.completed)


@router.get("/setup/bus-activity", tags=["setup"], summary="Kurz mithören: welche CAN-IDs sind auf dem Bus?")
async def bus_activity(
    channel: str = "default", seconds: float = 1.0, p: Platform = PlatformDep
) -> dict[str, Any]:
    """Wertet die in ``seconds`` (max. 5 s) empfangenen Frames aus – hilft bei Bitrate und IDs."""
    import asyncio
    import time

    p.connections.get(channel)  # NotConnectedError, falls nicht verbunden
    seconds = max(0.1, min(seconds, 5.0))
    start = time.time()
    await asyncio.sleep(seconds)
    ids: dict[tuple[int, bool], dict[str, Any]] = {}
    errors = 0
    total = 0
    for f in list(p.trace.frames):
        if f["ts"] < start or f["channel"] != channel or f["dir"] != "rx":
            continue
        if f["err"]:
            errors += 1
            continue
        total += 1
        key = (f["id"], f["ext"])
        entry = ids.setdefault(key, {"id": f["id"], "id_hex": f["id_hex"], "ext": f["ext"], "count": 0})
        entry["count"] += 1
        entry["data"] = f["data"]
    return {
        "channel": channel,
        "seconds": seconds,
        "frames": total,
        "error_frames": errors,
        "ids": sorted(ids.values(), key=lambda e: -e["count"])[:50],
    }
