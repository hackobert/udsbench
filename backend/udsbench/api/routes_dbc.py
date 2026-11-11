"""DBC-Bereich: Dateien verwalten, je Kanal zuordnen, Live-Signale, Botschaften kodieren/senden."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..can.frame import CanFrame
from ..core.platform import Platform
from ..dbc.store import signal_info
from .deps import Auth, PlatformDep

router = APIRouter(prefix="/api/v1", dependencies=[Auth])


def _channels(p: Platform) -> list[str]:
    """Bekannte Kanäle: verbundene, zugeordnete, aus ECU-Profilen und gespeicherten Verbindungen."""
    names = set(p.connections.channels) | set(p.dbc.assignments)
    names |= {r.profile.channel for r in p.packages.merged.ecus.values()}
    names |= {s.name for s in p.config.connections} | {s.name for s in p.setup.connections()}
    names.add("default")
    return sorted(names)


@router.get("/dbc", tags=["dbc"], summary="DBC-Dateien, Kanalzuordnung und Konflikte")
async def dbc_overview(p: Platform = PlatformDep) -> dict[str, Any]:
    connected = {n for n, ch in p.connections.channels.items() if ch.is_open}
    return {
        "files": p.dbc.list_items(),
        "assignments": {k: v for k, v in p.dbc.assignments.items() if v},
        "channels": [{"name": n, "connected": n in connected} for n in _channels(p)],
        "conflicts": p.dbc.conflicts(),
    }


class DbcUpload(BaseModel):
    filename: str = Field(..., description="Dateiname, z. B. powertrain.dbc")
    content: str = Field(..., description="Inhalt der DBC-Datei (Text)")
    overwrite: bool = False
    channels: list[str] = Field(default_factory=list, description="Gleich diesen Kanälen zuordnen")


@router.post("/dbc", tags=["dbc"], summary="DBC-Datei hochladen")
async def dbc_upload(body: DbcUpload, p: Platform = PlatformDep) -> dict[str, Any]:
    f = p.dbc.add(body.filename, body.content, overwrite=body.overwrite)
    for ch in body.channels:
        p.dbc.assign(ch, [*p.dbc.assignments.get(ch, []), f.id])
    return {"ok": True, "file": f.summary()}


@router.get("/dbc/files/{fid}", tags=["dbc"], summary="Inhalt einer DBC: Botschaften und Signale")
async def dbc_file(fid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.dbc.describe_file(fid)


@router.delete("/dbc/files/{fid}", tags=["dbc"], summary="DBC-Datei löschen")
async def dbc_delete(fid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.dbc.delete(fid)
    return {"ok": True}


class AssignIn(BaseModel):
    files: list[str] = Field(default_factory=list, description="DBC-IDs in Prioritätsreihenfolge")


@router.put("/dbc/channels/{channel}", tags=["dbc"], summary="DBCs eines Kanals festlegen")
async def dbc_assign(channel: str, body: AssignIn, p: Platform = PlatformDep) -> dict[str, Any]:
    ids = p.dbc.assign(channel, body.files)
    return {"ok": True, "channel": channel, "files": ids, "conflicts": p.dbc.conflicts().get(channel, [])}


@router.get("/dbc/channels/{channel}/messages", tags=["dbc"], summary="Botschaften aller DBCs eines Kanals")
async def dbc_channel_messages(channel: str, p: Platform = PlatformDep) -> list[dict[str, Any]]:
    out = []
    for fid in p.dbc.assignments.get(channel, []):
        f = p.dbc.get(fid)
        for m in sorted(f.db.messages, key=lambda m: m.frame_id):
            out.append(
                {
                    "dbc": fid,
                    "name": m.name,
                    "id": m.frame_id,
                    "id_hex": f"{m.frame_id:X}",
                    "extended": bool(m.is_extended_frame),
                    "fd": bool(getattr(m, "is_fd", False)),
                    "length": m.length,
                    "signals": [signal_info(s) for s in m.signals],
                }
            )
    return out


@router.get("/dbc/live", tags=["dbc"], summary="Zuletzt empfangene Werte je Botschaft eines Kanals")
async def dbc_live(channel: str = "default", p: Platform = PlatformDep) -> dict[str, Any]:
    return {"channel": channel, "messages": p.dbc.live_items(channel)}


@router.delete("/dbc/live", tags=["dbc"], summary="Live-Werte eines Kanals zurücksetzen")
async def dbc_live_reset(channel: str = "default", p: Platform = PlatformDep) -> dict[str, Any]:
    p.dbc.live.pop(channel, None)
    return {"ok": True}


class EncodeIn(BaseModel):
    channel: str = "default"
    message: str
    dbc: str | None = Field(None, description="DBC-ID; leer = alle DBCs des Kanals durchsuchen")
    signals: dict[str, Any] = Field(
        default_factory=dict, description="Signalwerte (physikalisch / Choice-Name)"
    )
    send: bool = Field(False, description="Kodierten Frame auf dem Kanal senden")


@router.post("/dbc/encode", tags=["dbc"], summary="Botschaft aus Signalwerten kodieren (optional senden)")
async def dbc_encode(body: EncodeIn, p: Platform = PlatformDep) -> dict[str, Any]:
    msg, fid = p.dbc.find_message(body.channel, body.message, body.dbc)
    data = p.dbc.encode(msg, body.signals)
    result: dict[str, Any] = {
        "dbc": fid,
        "message": msg.name,
        "id": msg.frame_id,
        "id_hex": f"{msg.frame_id:X}",
        "extended": bool(msg.is_extended_frame),
        "data": data.hex(" ").upper(),
        "sent": False,
    }
    if body.send:
        fd = bool(getattr(msg, "is_fd", False)) or len(data) > 8
        frame = CanFrame(
            arbitration_id=msg.frame_id, data=data, is_extended_id=bool(msg.is_extended_frame), is_fd=fd
        )
        await p.connections.get(body.channel).send(frame)
        result["sent"] = True
    return result
