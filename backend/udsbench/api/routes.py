"""REST-API ``/api/v1`` – deckt den gesamten Funktionsumfang ab (UI ist reiner Client)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ..can.adapters import list_interfaces
from ..can.frame import CanFrame
from ..config.loader import dump_package, load_structured
from ..config.schema import AppConfig, ConnectionSpec, Package, TesterPresentConfig, UdsTiming
from ..config.workspace import Workspace
from ..core.context import correlated, new_id
from ..core.errors import NotFoundError, ValidationFailed
from ..core.hexutil import parse_hex, parse_int, to_hex
from ..core.platform import Platform
from ..core.trace import TraceFilter
from ..isotp.codec import IsoTpError, preview_frames, stmin_to_text
from ..isotp.profile import IsoTpProfile
from ..logs.setup import get_buffer
from ..logs.traceformats import FORMATS, export_frames
from ..messages.engine import Engine, ExecContext
from ..messages.expr import render_payload, resolve_value
from ..messages.models import MessageDef, SequenceDef, Step, TransferAction
from ..plugins.registry import registry
from ..testrunner.models import SuiteDef, TestDef
from ..uds.codec import decode_response, describe_payload, validate_request
from ..uds.nrc import nrc_table_list
from ..uds.services import DTC_STATUS_BITS, SERVICES
from .deps import Auth, PlatformDep

router = APIRouter(prefix="/api/v1", dependencies=[Auth])


def _ok(**kw: Any) -> dict[str, Any]:
    return {"ok": True, **kw}


# =============================================================================================
# System
# =============================================================================================


@router.get("/info", tags=["system"], summary="Version, Status, aktive Pakete, Verbindungen")
async def info(p: Platform = PlatformDep) -> dict[str, Any]:
    return p.info()


@router.get("/plugins", tags=["system"])
async def plugins() -> dict[str, Any]:
    return registry.summary()


# =============================================================================================
# Verbindung
# =============================================================================================


@router.get("/interfaces", tags=["connection"], summary="Verfügbare CAN-Backends/-Interfaces")
async def interfaces(detect: bool = False) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, list_interfaces, detect), 15)
    except TimeoutError:
        return {**list_interfaces(False), "detect_error": "Timeout bei der Interface-Erkennung"}


@router.get("/connection", tags=["connection"], summary="Status aller Kanäle")
async def connection_status(p: Platform = PlatformDep) -> dict[str, Any]:
    return {"channels": p.connections.status(), "simulation": p.sim.status()}


@router.post("/connection", tags=["connection"], summary="Kanal verbinden")
async def connect(spec: ConnectionSpec, p: Platform = PlatformDep) -> dict[str, Any]:
    status = await p.connect(spec)
    return _ok(channel=status, ecus=p.diag.states(), simulation=[s["ecu"] for s in p.sim.status()])


@router.delete("/connection", tags=["connection"], summary="Kanal trennen")
async def disconnect(name: str = "default", p: Platform = PlatformDep) -> dict[str, Any]:
    await p.connections.disconnect(name)
    return _ok()


@router.post("/connection/{name}/reset", tags=["connection"], summary="Bus-/Adapter-Reset")
async def reset_channel(name: str, p: Platform = PlatformDep) -> dict[str, Any]:
    await p.connections.reset(name)
    return _ok(channel=p.connections.channels[name].status())


class RawFrameIn(BaseModel):
    channel: str = "default"
    id: str | int
    data: str = ""
    extended: bool = False
    fd: bool = False
    brs: bool = False


@router.post("/can/send", tags=["connection"], summary="Roh-Frame senden (umgeht ISO-TP)")
async def can_send(body: RawFrameIn, p: Platform = PlatformDep) -> dict[str, Any]:
    data = parse_hex(body.data)
    if len(data) > (64 if body.fd else 8):
        raise ValidationFailed("Zu viele Datenbytes für den Frame-Typ")
    cid = parse_int(body.id) if isinstance(body.id, str) else body.id
    frame = await p.connections.get(body.channel).send(CanFrame(cid, data, body.extended, body.fd, body.brs))
    return _ok(frame=frame.to_dict())


# =============================================================================================
# Konfiguration & Pakete
# =============================================================================================


def _masked_config(cfg: AppConfig) -> dict[str, Any]:
    d = cfg.model_dump(mode="json")
    if d["server"].get("token"):
        d["server"]["token"] = "***"
    return d


@router.get("/config", tags=["config"], summary="App-Konfiguration (Token maskiert)")
async def get_config(p: Platform = PlatformDep) -> dict[str, Any]:
    return _masked_config(p.config)


class ConfigUpdate(BaseModel):
    timing: UdsTiming | None = None
    tester_present: TesterPresentConfig | None = None
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"] | None = None
    mask_secrets: bool | None = None


@router.put(
    "/config", tags=["config"], summary="Laufzeit-Konfiguration ändern (Timing, Keep-Alive, Log-Level)"
)
async def put_config(body: ConfigUpdate, p: Platform = PlatformDep) -> dict[str, Any]:
    import logging

    from ..logs.setup import TRACE, get_masker

    if body.timing:
        p.config.timing = body.timing
    if body.tester_present:
        p.config.tester_present = body.tester_present
    if body.log_level:
        p.config.logging.level = body.log_level
        logging.getLogger("udsbench").setLevel(
            TRACE if body.log_level == "TRACE" else getattr(logging, body.log_level)
        )
    if body.mask_secrets is not None:
        p.config.logging.mask_secrets = body.mask_secrets
        get_masker().enabled = body.mask_secrets
        p.security.mask = body.mask_secrets
    p.diag.close_all()
    p.diag.rebuild()
    return _masked_config(p.config)


@router.get("/config/schema", tags=["config"], summary="JSON-Schema für Pakete bzw. App-Konfiguration")
async def config_schema(
    kind: Literal["package", "app", "test", "sequence", "message", "step"] = "package",
) -> dict[str, Any]:
    model = {
        "package": Package,
        "app": AppConfig,
        "test": TestDef,
        "sequence": SequenceDef,
        "message": MessageDef,
        "step": Step,
    }[kind]
    return model.model_json_schema(by_alias=True)  # type: ignore[attr-defined, no-any-return]


class PackageUpload(BaseModel):
    content: str | dict[str, Any] = Field(..., description="YAML/JSON-Text oder Objekt")
    format: Literal["yaml", "json"] | None = None
    overwrite: bool = False
    activate: bool = False


def _parse_upload(body: PackageUpload) -> Any:
    return body.content if isinstance(body.content, dict) else load_structured(body.content, body.format)


@router.post("/config/validate", tags=["config"], summary="Paket validieren ohne zu speichern")
async def validate_package(body: PackageUpload) -> dict[str, Any]:
    from ..config.loader import parse_package

    pkg = parse_package(_parse_upload(body))
    return _ok(package=pkg.package.model_dump())


@router.post("/config/import", tags=["config"], summary="Konfig-Paket importieren (YAML/JSON)")
async def config_import(body: PackageUpload, p: Platform = PlatformDep) -> dict[str, Any]:
    entry = p.packages.add(_parse_upload(body), overwrite=body.overwrite, activate=body.activate)
    await p.settle()
    return _ok(package=entry.summary(entry.id in p.packages.active))


@router.get("/config/export", tags=["config"], summary="Paket exportieren (YAML/JSON)")
async def config_export(
    package: str, format: Literal["yaml", "json"] = "yaml", p: Platform = PlatformDep
) -> Response:
    entry = p.packages.get(package)
    text = dump_package(entry.package, format)
    return PlainTextResponse(
        text,
        media_type="application/json" if format == "json" else "application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{package}.{format}"'},
    )


@router.get("/packages", tags=["packages"], summary="Alle Pakete inkl. ungültiger Dateien")
async def packages(p: Platform = PlatformDep) -> dict[str, Any]:
    return {"packages": p.packages.list_items(), "active": p.packages.active, "invalid": p.packages.invalid}


@router.post("/packages", tags=["packages"], summary="Paket anlegen/hochladen")
async def add_package(body: PackageUpload, p: Platform = PlatformDep) -> dict[str, Any]:
    return await config_import(body, p)


@router.get("/packages/{pid}", tags=["packages"])
async def get_package(pid: str, format: Literal["json", "yaml"] = "json", p: Platform = PlatformDep) -> Any:
    entry = p.packages.get(pid)
    if format == "yaml":
        return PlainTextResponse(dump_package(entry.package, "yaml"), media_type="application/x-yaml")
    return {
        "summary": entry.summary(pid in p.packages.active),
        "content": entry.package.model_dump(mode="json", by_alias=True),
    }


@router.delete("/packages/{pid}", tags=["packages"])
async def delete_package(pid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.packages.delete(pid)
    await p.settle()
    return _ok()


@router.post("/packages/{pid}/activate", tags=["packages"])
async def activate_package(pid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.packages.activate(pid)
    await p.settle()
    return _ok(active=p.packages.active)


@router.post("/packages/{pid}/deactivate", tags=["packages"])
async def deactivate_package(pid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.packages.deactivate(pid)
    await p.settle()
    return _ok(active=p.packages.active)


@router.put("/packages/active", tags=["packages"], summary="Menge aktiver Pakete setzen")
async def set_active(ids: list[str] = Body(...), p: Platform = PlatformDep) -> dict[str, Any]:
    p.packages.set_active(ids)
    await p.settle()
    return _ok(active=p.packages.active)


@router.post("/packages/rescan", tags=["packages"], summary="Paketverzeichnisse neu einlesen")
async def rescan(p: Platform = PlatformDep) -> dict[str, Any]:
    active = list(p.packages.active)
    p.packages.scan()
    p.packages.set_active([a for a in active if a in p.packages.entries])
    await p.settle()
    return {"packages": p.packages.list_items(), "invalid": p.packages.invalid}


# =============================================================================================
# ECUs / ISO-TP
# =============================================================================================


@router.get("/ecus", tags=["ecus"], summary="ECU-Profile inkl. Session-/Security-Zustand")
async def ecus(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    out = []
    for st in p.diag.states():
        rdef = p.packages.merged.ecus[st["id"]]
        st["sessions"] = [s.model_dump() for s in rdef.ecu.sessions]
        st["security_levels"] = [lv.model_dump() for lv in rdef.ecu.security_levels]
        st["functional_group"] = rdef.ecu.functional_group
        st["description"] = rdef.ecu.description
        out.append(st)
    return out


@router.get("/ecus/{ecu}", tags=["ecus"])
async def ecu(ecu: str, p: Platform = PlatformDep) -> dict[str, Any]:
    for st in await ecus(p):
        if st["id"] == ecu:
            return st
    raise NotFoundError(f"ECU {ecu!r} nicht gefunden")


class SessionIn(BaseModel):
    session: int | str


@router.post("/ecus/{ecu}/session", tags=["ecus"], summary="DiagnosticSessionControl")
async def ecu_session(ecu: str, body: SessionIn, p: Platform = PlatformDep) -> dict[str, Any]:
    rt = p.diag.get(ecu)
    res = await rt.request(bytes([0x10, rt.resolve_session(body.session)]))
    return {"result": res.to_dict(), "state": rt.state()}


class TesterPresentIn(BaseModel):
    enabled: bool


@router.put("/ecus/{ecu}/tester-present", tags=["ecus"], summary="Keep-Alive ein/aus")
async def ecu_tp(ecu: str, body: TesterPresentIn, p: Platform = PlatformDep) -> dict[str, Any]:
    rt = p.diag.get(ecu)
    rt.tp_enabled = body.enabled
    return rt.state()


@router.get("/isotp/profiles", tags=["isotp"])
async def isotp_profiles(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    users: dict[str, list[str]] = {}
    for eid, r in p.packages.merged.ecus.items():
        users.setdefault(r.profile.name, []).append(eid)
    return [
        {
            **prof.model_dump(mode="json"),
            "ecus": users.get(name, []),
            "tx_dl": prof.tx_dl,
            "st_min_text": stmin_to_text(prof.st_min),
        }
        for name, prof in p.packages.merged.profiles.items()
    ]


@router.put(
    "/isotp/profiles/{name}", tags=["isotp"], summary="Profil live ändern (Laufzeit, nicht persistiert)"
)
async def put_isotp_profile(name: str, profile: IsoTpProfile, p: Platform = PlatformDep) -> dict[str, Any]:
    merged = p.packages.merged
    if name not in merged.profiles:
        raise NotFoundError(f"ISO-TP-Profil {name!r} nicht gefunden")
    profile = profile.model_copy(update={"name": name})
    merged.profiles[name] = profile
    for r in merged.ecus.values():
        if r.profile.name == name:
            r.profile = profile
    p.trace.update_endpoints()
    p.diag.rebuild()
    return _ok(
        profile=profile.model_dump(mode="json"), note="Laufzeitänderung – zum Dauerhaften im Paket speichern"
    )


# =============================================================================================
# UDS
# =============================================================================================


@router.get("/uds/services", tags=["uds"], summary="Servicekatalog ISO 14229-1")
async def uds_services() -> dict[str, Any]:
    return {"services": [s.to_dict() for s in SERVICES.values()], "dtc_status_bits": DTC_STATUS_BITS}


@router.get("/uds/nrc", tags=["uds"], summary="Vollständige NRC-Tabelle")
async def uds_nrc() -> list[dict[str, Any]]:
    return nrc_table_list()


class UdsRequestIn(BaseModel):
    ecu: str | None = None
    payload: str = Field(..., description="Hex-Nutzlast, z. B. '22 F1 00'; ${...}-Platzhalter erlaubt")
    functional: bool = False
    timeout_ms: float | None = None
    validate_mode: Literal["strict", "warn", "off"] | None = Field(None, alias="validate")
    vars: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


@router.post("/uds/request", tags=["uds"], summary="UDS-Request senden → dekodierte Response")
async def uds_request(body: UdsRequestIn, p: Platform = PlatformDep) -> dict[str, Any]:
    rt = p.diag.get(body.ecu)
    payload = render_payload(body.payload, {**body.vars}) if "${" in body.payload else parse_hex(body.payload)
    with correlated(new_id("req_")):
        res = await rt.request(
            payload, functional=body.functional, timeout_ms=body.timeout_ms, validate=body.validate_mode
        )
    return res.to_dict()


class PayloadIn(BaseModel):
    payload: str
    request: str | None = None
    ecu: str | None = None
    profile: IsoTpProfile | None = None
    functional: bool = False


@router.post("/uds/validate", tags=["uds"], summary="Request validieren")
async def uds_validate(body: PayloadIn) -> dict[str, Any]:
    payload = parse_hex(body.payload)
    return {**validate_request(payload).to_dict(), "description": describe_payload(payload)}


@router.post("/uds/decode", tags=["uds"], summary="Response/Request dekodieren")
async def uds_decode(body: PayloadIn, p: Platform = PlatformDep) -> dict[str, Any]:
    payload = parse_hex(body.payload)
    req = parse_hex(body.request) if body.request else None
    return {
        "decoded": decode_response(payload, req, p.packages.merged.catalogs),
        "description": describe_payload(payload, p.packages.merged.catalogs),
    }


@router.post(
    "/uds/preview",
    tags=["uds"],
    summary="Byte-/Frame-Vorschau nach ISO-TP-Framing (PCI, Adressbyte, Padding)",
)
async def uds_preview(body: PayloadIn, p: Platform = PlatformDep) -> dict[str, Any]:
    payload = parse_hex(body.payload)
    if body.profile is not None:
        prof = body.profile
    else:
        if body.ecu is None:
            raise ValidationFailed("'ecu' oder 'profile' angeben")
        rdef = p.packages.merged.ecus.get(body.ecu)
        if rdef is None:
            raise NotFoundError(f"ECU {body.ecu!r} nicht gefunden")
        prof = rdef.profile
    try:
        frames = preview_frames(payload, prof, body.functional)
    except IsoTpError as exc:
        raise ValidationFailed(str(exc)) from exc
    v = validate_request(payload)
    return {
        "payload": to_hex(payload),
        "length": len(payload),
        "validation": v.to_dict(),
        "description": describe_payload(payload, p.packages.merged.catalogs),
        "profile": {
            "name": prof.name,
            "addressing": prof.addressing,
            "padding": prof.padding.model_dump(),
            "dlc_mode": prof.dlc_mode,
            "can_fd": prof.can_fd,
            "tx_dl": prof.tx_dl,
        },
        "frames": [f.to_dict() for f in frames],
        "flow_control_expected": len(frames) > 1,
    }


# =============================================================================================
# Kataloge & Komfortfunktionen (DID/DTC/Routinen/IO/Transfer)
# =============================================================================================


@router.get("/catalogs/dids", tags=["catalogs"])
async def cat_dids(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return [d.to_public() for d in sorted(p.packages.merged.catalogs.dids.values(), key=lambda x: x.id)]


@router.get("/catalogs/dtcs", tags=["catalogs"])
async def cat_dtcs(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return [d.to_public() for d in sorted(p.packages.merged.catalogs.dtcs.values(), key=lambda x: x.code)]


@router.get("/catalogs/routines", tags=["catalogs"])
async def cat_routines(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return [r.to_public() for r in sorted(p.packages.merged.catalogs.routines.values(), key=lambda x: x.id)]


async def _run_step(
    p: Platform, step: dict[str, Any], ecu: str | None, vars: dict[str, Any] | None = None
) -> dict[str, Any]:
    st = Step.model_validate(step)
    engine = Engine(p)
    ctx = ExecContext(p, vars=dict(vars or {}), ecu=ecu)
    with correlated(new_id("req_")) as cid:
        await engine.run_step(st, ctx)
    rec = ctx.records[-1]
    return {
        "cid": cid,
        "step": rec.to_dict(),
        "result": ctx.last.to_dict() if ctx.last else None,
        "vars": {k: (to_hex(v) if isinstance(v, (bytes, bytearray)) else v) for k, v in ctx.vars.items()},
    }


class DidReadIn(BaseModel):
    ecu: str | None = None
    dids: list[int | str]


@router.post("/dids/read", tags=["catalogs"], summary="ReadDataByIdentifier (typgerecht dekodiert)")
async def did_read(body: DidReadIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(p, {"read_did": body.dids, "expect": {}}, body.ecu)


class DidWriteIn(BaseModel):
    ecu: str | None = None
    did: int | str
    value: Any = None
    raw: str | None = None


@router.post("/dids/write", tags=["catalogs"], summary="WriteDataByIdentifier (typgerecht kodiert)")
async def did_write(body: DidWriteIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(
        p, {"write_did": {"did": body.did, "value": body.value, "raw": body.raw}, "expect": {}}, body.ecu
    )


class IoIn(BaseModel):
    ecu: str | None = None
    did: int | str
    parameter: int | str = 0x03
    value: Any = None
    raw: str | None = None


@router.post("/dids/io-control", tags=["catalogs"], summary="InputOutputControlByIdentifier")
async def io_control(body: IoIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(
        p,
        {
            "io_control": {
                "did": body.did,
                "parameter": body.parameter,
                "value": body.value,
                "raw": body.raw,
            },
            "expect": {},
        },
        body.ecu,
    )


class DtcReadIn(BaseModel):
    ecu: str | None = None
    subfunction: int | str = 0x02
    mask: int | str = 0xFF
    extra: str | None = None


@router.post("/dtcs/read", tags=["catalogs"], summary="ReadDTCInformation")
async def dtc_read(body: DtcReadIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(p, {"read_dtc": body.model_dump(exclude={"ecu"}), "expect": {}}, body.ecu)


class DtcClearIn(BaseModel):
    ecu: str | None = None
    group: int | str = 0xFFFFFF


@router.post("/dtcs/clear", tags=["catalogs"], summary="ClearDiagnosticInformation")
async def dtc_clear(body: DtcClearIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(p, {"clear_dtc": body.group, "expect": {}}, body.ecu)


class RoutineIn(BaseModel):
    ecu: str | None = None
    routine: int | str
    action: Literal["start", "stop", "results"] = "start"
    params: dict[str, Any] = Field(default_factory=dict)
    raw: str | None = None


@router.post("/routines/control", tags=["catalogs"], summary="RoutineControl (0x31)")
async def routine_control(body: RoutineIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(
        p,
        {
            "routine": {"id": body.routine, "action": body.action, "params": body.params, "raw": body.raw},
            "expect": {},
        },
        body.ecu,
    )


class TransferIn(TransferAction):
    ecu: str | None = None


@router.post("/transfer", tags=["catalogs"], summary="Geführter Download/Upload (0x34/0x35 → 0x36 … → 0x37)")
async def transfer(body: TransferIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(p, {"transfer": body.model_dump(exclude={"ecu"}, exclude_none=True)}, body.ecu)


class StepIn(BaseModel):
    ecu: str | None = None
    step: dict[str, Any]
    vars: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/steps/run", tags=["sequences"], summary="Einen beliebigen Schritt ausführen (Konsole/Automation)"
)
async def run_step(body: StepIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await _run_step(p, body.step, body.ecu, body.vars)


# =============================================================================================
# Botschaften, Sequenzen, Tests (CRUD im Arbeitsbereich)
# =============================================================================================


def _crud(kind: str, model: type[BaseModel], getter: Any) -> None:
    tag = kind

    @router.get(f"/{kind}", tags=[tag], name=f"list_{kind}")
    async def _list(p: Platform = PlatformDep) -> list[dict[str, Any]]:
        merged = p.packages.merged
        return [
            {
                **v.model_dump(mode="json", by_alias=True, exclude_none=True),
                "package": merged.origin.get(f"{kind[:-1]}:{k}"),
            }
            for k, v in getter(merged).items()
        ]

    @router.get(f"/{kind}/{{item_id}}", tags=[tag], name=f"get_{kind}")
    async def _get(item_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
        merged = p.packages.merged
        item = getter(merged).get(item_id)
        if item is None:
            raise NotFoundError(f"{item_id!r} nicht gefunden")
        return {
            **item.model_dump(mode="json", by_alias=True, exclude_none=True),
            "package": merged.origin.get(f"{kind[:-1]}:{item_id}"),
        }

    @router.post(
        f"/{kind}", tags=[tag], name=f"create_{kind}", summary=f"{kind[:-1]} im Arbeitsbereich anlegen"
    )
    async def _create(item: dict[str, Any] = Body(...), p: Platform = PlatformDep) -> dict[str, Any]:
        obj = model.model_validate(item)
        Workspace(p.packages).upsert(
            kind, obj.model_dump(mode="json", by_alias=True, exclude_none=True), create=True
        )
        await p.settle()
        return _ok(id=obj.id)  # type: ignore[attr-defined]

    @router.put(f"/{kind}/{{item_id}}", tags=[tag], name=f"update_{kind}")
    async def _update(
        item_id: str, item: dict[str, Any] = Body(...), p: Platform = PlatformDep
    ) -> dict[str, Any]:
        item["id"] = item_id
        obj = model.model_validate(item)
        Workspace(p.packages).upsert(
            kind, obj.model_dump(mode="json", by_alias=True, exclude_none=True), create=False
        )
        await p.settle()
        return _ok(id=item_id)

    @router.delete(f"/{kind}/{{item_id}}", tags=[tag], name=f"delete_{kind}")
    async def _delete(item_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
        Workspace(p.packages).delete(kind, item_id)
        await p.settle()
        return _ok()


class SendMessageIn(BaseModel):
    ecu: str | None = None
    vars: dict[str, Any] = Field(default_factory=dict)
    functional: bool | None = None


@router.post("/messages/{mid}/send", tags=["messages"], summary="Vordefinierte Botschaft senden")
async def send_message(
    mid: str, body: SendMessageIn | None = None, p: Platform = PlatformDep
) -> dict[str, Any]:
    body = body or SendMessageIn()
    msg = p.packages.merged.messages.get(mid)
    if msg is None:
        raise NotFoundError(f"Botschaft {mid!r} nicht gefunden")
    step: dict[str, Any] = {"send": {"message": mid, "vars": body.vars}}
    if body.functional is not None:
        step["send"]["functional"] = body.functional
    return await _run_step(p, step, body.ecu or msg.ecu)


@router.post("/messages/{mid}/preview", tags=["messages"], summary="Vorlage auflösen (ohne Senden)")
async def preview_message(
    mid: str, body: SendMessageIn | None = None, p: Platform = PlatformDep
) -> dict[str, Any]:
    body = body or SendMessageIn()
    msg = p.packages.merged.messages.get(mid)
    if msg is None:
        raise NotFoundError(f"Botschaft {mid!r} nicht gefunden")
    ctx = ExecContext(p, vars={}, ecu=body.ecu or msg.ecu)
    env = ctx.env()
    env.update({k: resolve_value(v, env) for k, v in msg.vars.items()})
    env.update({k: resolve_value(v, env) for k, v in body.vars.items()})
    payload = render_payload(msg.payload, env)
    return {"payload": to_hex(payload), "description": describe_payload(payload, p.packages.merged.catalogs)}


class RunIn(BaseModel):
    ecu: str | None = None
    vars: dict[str, Any] = Field(default_factory=dict)
    wait: bool = Field(False, description="Bis zum Ende warten und den Report direkt zurückgeben")
    timeout_s: float = 3600


async def _run_response(p: Platform, run: Any, body: RunIn) -> dict[str, Any]:
    if body.wait:
        await p.runner.wait(run.id, body.timeout_s)
        return run.to_dict()  # type: ignore[no-any-return]
    return run.to_dict(detail=False)  # type: ignore[no-any-return]


@router.post(
    "/sequences/{sid}/run", tags=["sequences"], summary="Sequenz ausführen (Lauf mit Schrittprotokoll)"
)
async def run_sequence(sid: str, body: RunIn | None = None, p: Platform = PlatformDep) -> dict[str, Any]:
    body = body or RunIn()
    return await _run_response(p, p.runner.start_sequence(sid, body.vars, body.ecu), body)


@router.post("/tests/{tid}/run", tags=["tests"], summary="Einzeltest ausführen")
async def run_test(tid: str, body: RunIn | None = None, p: Platform = PlatformDep) -> dict[str, Any]:
    body = body or RunIn()
    return await _run_response(p, p.runner.start_test(tid, body.vars, body.ecu), body)


@router.post("/testsuites/{sid}/run", tags=["tests"], summary="Testsuite ausführen")
async def run_suite(sid: str, body: RunIn | None = None, p: Platform = PlatformDep) -> dict[str, Any]:
    body = body or RunIn()
    return await _run_response(p, p.runner.start_suite(sid, body.vars, body.ecu), body)


class AdhocTestIn(RunIn):
    test: dict[str, Any]


@router.post("/tests/run-adhoc", tags=["tests"], summary="Test-Definition direkt ausführen (ohne Speichern)")
async def run_adhoc(body: AdhocTestIn, p: Platform = PlatformDep) -> dict[str, Any]:
    t = TestDef.model_validate(body.test)
    run = p.runner.start_adhoc("test", t.id, t.name or t.id, [t], body.vars, body.ecu)
    return await _run_response(p, run, body)


@router.get("/runs", tags=["tests"], summary="Testläufe (laufend und gespeichert)")
async def runs(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return p.runner.list_items()


@router.get("/runs/{run_id}", tags=["tests"], summary="Status/Report eines Laufs")
async def get_run(run_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.runner.get(run_id).to_dict()  # type: ignore[no-any-return]


@router.get(
    "/runs/{run_id}/report",
    tags=["tests"],
    summary="Report als JSON, JUnit-XML, HTML oder ZIP (inkl. Traces/Logs)",
)
async def run_report(
    run_id: str, format: Literal["json", "junit", "html", "zip"] = "json", p: Platform = PlatformDep
) -> Response:
    if format == "html":
        return HTMLResponse(p.reports.run_html(run_id))
    if format == "zip":
        return Response(
            p.reports.run_bundle(run_id),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
        )
    text = p.runner.report(run_id, format)
    media = "application/xml" if format == "junit" else "application/json"
    ext = "xml" if format == "junit" else "json"
    return PlainTextResponse(
        text, media_type=media, headers={"Content-Disposition": f'attachment; filename="{run_id}.{ext}"'}
    )


@router.post("/runs/{run_id}/cancel", tags=["tests"])
async def cancel_run(run_id: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.runner.cancel(run_id)
    return _ok()


# =============================================================================================
# Security Access
# =============================================================================================


@router.get("/security/providers", tags=["security"])
async def sec_providers(p: Platform = PlatformDep) -> dict[str, Any]:
    from ..security.providers import PROVIDER_TYPES

    return {"providers": p.security.list_providers(), "types": sorted(PROVIDER_TYPES)}


class SeedIn(BaseModel):
    ecu: str
    level: int | str = 1


@router.post("/security/seed", tags=["security"], summary="Seed anfordern (0x27 ungerade)")
async def sec_seed(body: SeedIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return await p.security.request_seed(body.ecu, parse_int(body.level))


class KeyIn(BaseModel):
    ecu: str
    level: int | str = 1
    key: str | None = Field(None, description="Hex-Key; leer = aus 'seed' bzw. letztem Seed berechnen")
    seed: str | None = None


@router.post("/security/key", tags=["security"], summary="Key senden (0x27 gerade)")
async def sec_key(body: KeyIn, p: Platform = PlatformDep) -> dict[str, Any]:
    level = parse_int(body.level)
    if body.key:
        key = parse_hex(body.key)
    else:
        rt = p.diag.get(body.ecu)
        seed = parse_hex(body.seed) if body.seed else rt.last_seed.get(level)
        if not seed:
            raise ValidationFailed("Kein Key und kein Seed vorhanden")
        key = await p.security.compute_key(body.ecu, level, seed)
    return await p.security.send_key(body.ecu, level, key)


class ComputeIn(BaseModel):
    ecu: str | None = None
    level: int | str = 1
    seed: str
    provider: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/security/compute-key", tags=["security"], summary="Manuelle Seed→Key-Berechnung über Provider")
async def sec_compute(body: ComputeIn, p: Platform = PlatformDep) -> dict[str, Any]:
    key = await p.security.compute_key(
        body.ecu, parse_int(body.level), parse_hex(body.seed), provider=body.provider, params=body.params
    )
    return {"key": to_hex(key), "length": len(key)}


class UnlockIn(BaseModel):
    ecu: str
    level: int | str = 1
    provider: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    switch_session: bool = True


@router.post("/security/unlock", tags=["security"], summary="Automatischer Unlock (Seed → Key → senden)")
async def sec_unlock(body: UnlockIn, p: Platform = PlatformDep) -> dict[str, Any]:
    with correlated(new_id("unlock_")):
        res = await p.security.unlock(
            body.ecu,
            parse_int(body.level),
            provider=body.provider,
            params=body.params,
            switch_session=body.switch_session,
        )
    return {k: v for k, v in res.items() if not k.startswith("_")}


class NrcSuiteIn(RunIn):
    ecu: str
    level: int | str = 1
    options: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/security/nrc-suite/cases", tags=["security"], summary="Generierte NRC-Provokationsfälle anzeigen"
)
async def nrc_cases(body: NrcSuiteIn, p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return [
        t.model_dump(mode="json", by_alias=True, exclude_none=True)
        for t in p.security.nrc_cases(body.ecu, parse_int(body.level), body.options)
    ]


@router.post("/security/nrc-suite/run", tags=["security"], summary="Negative-Response-Testsuite ausführen")
async def nrc_run(body: NrcSuiteIn, p: Platform = PlatformDep) -> dict[str, Any]:
    tests = p.security.nrc_cases(body.ecu, parse_int(body.level), body.options)
    run = p.runner.start_adhoc(
        "security_nrc",
        f"{body.ecu}/0x{parse_int(body.level):02X}",
        "Security-Access NRC-Testsuite",
        tests,
        body.vars,
        body.ecu,
    )
    return await _run_response(p, run, body)


# =============================================================================================
# Trace, Aufzeichnung & Replay
# =============================================================================================


@router.get(
    "/trace", tags=["trace"], summary="Trace-Puffer abfragen (Frames oder rekonstruierte Nachrichten)"
)
async def trace(
    view: Literal["frames", "messages"] = "frames",
    since: int = 0,
    limit: int = Query(1000, le=100000),
    ids: str | None = None,
    direction: str | None = None,
    only_uds: bool = False,
    services: str | None = None,
    data_contains: str | None = None,
    channel: str | None = None,
    p: Platform = PlatformDep,
) -> dict[str, Any]:
    flt = TraceFilter.from_dict(
        {
            "ids": ids,
            "direction": direction,
            "only_uds": only_uds,
            "services": services,
            "data_contains": data_contains,
            "channel": channel,
        }
    )
    items = p.trace.query(view, since, limit, flt)
    return {"items": items, "last_seq": items[-1]["seq"] if items else since, "bookmarks": p.trace.bookmarks}


@router.delete("/trace", tags=["trace"])
async def trace_clear(p: Platform = PlatformDep) -> dict[str, Any]:
    p.trace.clear()
    return _ok()


class BookmarkIn(BaseModel):
    seq: int
    note: str = ""


@router.post("/trace/bookmarks", tags=["trace"])
async def trace_bookmark(body: BookmarkIn, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.trace.add_bookmark(body.seq, body.note)


@router.get("/trace/export", tags=["trace"], summary="Trace-Puffer exportieren (csv, asc, candump, jsonl)")
async def trace_export(format: str = "csv", p: Platform = PlatformDep) -> Response:
    if format not in FORMATS:
        raise ValidationFailed(f"Format {format!r} unbekannt ({', '.join(FORMATS)})")
    frames = [CanFrame.from_dict(d) for d in p.trace.frames]
    return PlainTextResponse(
        export_frames(frames, format),
        headers={"Content-Disposition": f'attachment; filename="trace.{format}"'},
    )


@router.get("/recordings", tags=["recordings"])
async def recordings(p: Platform = PlatformDep) -> dict[str, Any]:
    return {
        "recordings": p.recorder.list_items(),
        "replays": p.recorder.replay_status(),
        "formats": list(FORMATS),
    }


class RecordStartIn(BaseModel):
    name: str | None = None
    channels: list[str] | None = None


@router.post("/recordings", tags=["recordings"], summary="Aufzeichnung starten")
async def rec_start(body: RecordStartIn | None = None, p: Platform = PlatformDep) -> dict[str, Any]:
    body = body or RecordStartIn()
    return p.recorder.start(body.name, body.channels)


@router.post("/recordings/stop", tags=["recordings"], summary="Aufzeichnung stoppen und speichern")
async def rec_stop(p: Platform = PlatformDep) -> dict[str, Any]:
    return p.recorder.stop()


class ImportIn(BaseModel):
    content: str
    name: str = "Import"
    format: str | None = None
    filename: str = ""


@router.post(
    "/recordings/import", tags=["recordings"], summary="Trace importieren (jsonl, csv, asc, candump)"
)
async def rec_import(body: ImportIn, p: Platform = PlatformDep) -> dict[str, Any]:
    try:
        return p.recorder.import_text(body.content, body.name, body.format, body.filename)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc


@router.get("/recordings/{rid}", tags=["recordings"], summary="Aufzeichnung exportieren")
async def rec_export(rid: str, format: str = "jsonl", p: Platform = PlatformDep) -> Response:
    if format not in FORMATS:
        raise ValidationFailed(f"Format {format!r} unbekannt")
    return PlainTextResponse(
        p.recorder.export(rid, format),
        headers={"Content-Disposition": f'attachment; filename="{rid}.{format}"'},
    )


@router.get("/recordings/{rid}/frames", tags=["recordings"], summary="Frames einer Aufzeichnung (JSON)")
async def rec_frames(rid: str, limit: int = 5000, p: Platform = PlatformDep) -> dict[str, Any]:
    frames, meta = p.recorder.load(rid)
    return {"meta": meta, "frames": [f.to_dict() for f in frames[:limit]], "total": len(frames)}


@router.delete("/recordings/{rid}", tags=["recordings"])
async def rec_delete(rid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.recorder.delete(rid)
    return _ok()


class ReplayIn(BaseModel):
    mode: Literal["bus", "trace"] = "bus"
    channel: str | None = None
    speed: float = Field(1.0, gt=0)
    directions: list[Literal["tx", "rx"]] | None = None
    loop: int = Field(1, ge=1, le=1000)


@router.post("/recordings/{rid}/replay", tags=["recordings"], summary="Replay auf den Bus oder in den Trace")
async def rec_replay(rid: str, body: ReplayIn | None = None, p: Platform = PlatformDep) -> dict[str, Any]:
    body = body or ReplayIn()
    return await p.recorder.replay(
        rid,
        mode=body.mode,
        channel=body.channel,
        speed=body.speed,
        directions=list(body.directions) if body.directions else None,
        loop_count=body.loop,
    )


@router.post("/replays/{rid}/cancel", tags=["recordings"])
async def replay_cancel(rid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.recorder.cancel_replay(rid)
    return _ok()


# =============================================================================================
# Logs
# =============================================================================================


@router.get("/logs", tags=["logs"], summary="Logs abfragen (Kanal, Level, Korrelations-ID, Text)")
async def logs(
    channel: Literal["app", "comm", "audit", "test"] | None = None,
    level: str | None = None,
    cid: str | None = None,
    since: int = 0,
    limit: int = Query(500, le=5000),
    q: str | None = None,
) -> dict[str, Any]:
    items = get_buffer().query(channel, level, cid, since, limit, q)
    return {"items": items, "last_seq": items[-1]["seq"] if items else since}


@router.get("/logs/stream", tags=["logs"], summary="Log-Stream (Server-Sent Events)")
async def logs_stream(
    request: Request, channel: str | None = None, level: str | None = None
) -> StreamingResponse:
    buf = get_buffer()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(5000)
    loop = asyncio.get_running_loop()

    def push(d: dict[str, Any]) -> None:
        def _put() -> None:
            if not queue.full():
                queue.put_nowait(d)

        loop.call_soon_threadsafe(_put)

    buf.subscribers.append(push)

    async def gen() -> Any:
        import logging

        min_level = logging.getLevelName(level) if level else 0
        try:
            yield ": udsbench log stream\n\n"
            while not await request.is_disconnected():
                try:
                    d = await asyncio.wait_for(queue.get(), 15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if channel and d["channel"] != channel:
                    continue
                if level and logging.getLevelName(d["level"]) < min_level:
                    continue
                yield f"data: {json.dumps(d, default=str, ensure_ascii=False)}\n\n"
        finally:
            if push in buf.subscribers:
                buf.subscribers.remove(push)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# =============================================================================================
# Simulation
# =============================================================================================


@router.get("/simulation", tags=["simulation"], summary="Zustand der ECU-Testdoubles")
async def sim_status(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return p.sim.status()


@router.post("/simulation/restart", tags=["simulation"])
async def sim_restart(p: Platform = PlatformDep) -> dict[str, Any]:
    return _ok(started=await p.sim.restart())


class SimValueIn(BaseModel):
    value: str


@router.put("/simulation/{ecu}/dids/{did}", tags=["simulation"], summary="DID-Wert im Testdouble setzen")
async def sim_did(ecu: str, did: str, body: SimValueIn, p: Platform = PlatformDep) -> dict[str, Any]:
    sim = p.sim.get(ecu)
    sim.dids[parse_int(did)] = bytearray(parse_hex(body.value))
    return sim.state()


class SimDtcIn(BaseModel):
    status: int | str


@router.put("/simulation/{ecu}/dtcs/{code}", tags=["simulation"], summary="DTC-Status im Testdouble setzen")
async def sim_dtc(ecu: str, code: str, body: SimDtcIn, p: Platform = PlatformDep) -> dict[str, Any]:
    sim = p.sim.get(ecu)
    sim.dtcs[int(code, 16)] = parse_int(body.status)
    return sim.state()


@router.post("/simulation/{ecu}/reset", tags=["simulation"], summary="Testdouble vollständig zurücksetzen")
async def sim_reset(ecu: str, p: Platform = PlatformDep) -> dict[str, Any]:
    sim = p.sim.get(ecu)
    sim.reset_state(full=True)
    return sim.state()


# CRUD-Routen registrieren
_crud("messages", MessageDef, lambda m: m.messages)
_crud("sequences", SequenceDef, lambda m: m.sequences)
_crud("tests", TestDef, lambda m: m.tests)
_crud("testsuites", SuiteDef, lambda m: m.testsuites)
