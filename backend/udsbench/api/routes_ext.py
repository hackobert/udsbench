"""API-Erweiterungen: Statistik/Timechart, Ereignis-Zeitleiste, Reports, Dashboards & Aktionen."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from ..core.errors import NotFoundError
from ..core.history import bucketize, frame_items
from ..core.platform import Platform
from ..dashboards.actions import run_action
from ..dashboards.models import Action, Dashboard
from ..reports.service import ReportSpec, auto_bucket, parse_time
from .deps import Auth, PlatformDep

router = APIRouter(prefix="/api/v1", dependencies=[Auth])


def _window(from_: str | None, to: str | None, default: str = "-5m") -> tuple[float, float]:
    now = time.time()
    t_to = parse_time(to or "now", now)
    t_from = parse_time(from_ or default, now)
    return t_from, t_to


# =============================================================================================
# Statistik / Timechart / Ereignisse
# =============================================================================================


@router.get(
    "/stats/timeseries", tags=["stats"], summary="Zeitreihe für die Timechart (Zählung je Bucket und Gruppe)"
)
async def timeseries(
    metric: Literal["uds", "frames", "events"] = "uds",
    group_by: str = Query(
        "type",
        description="uds: type|service|ecu|nrc_name|sid · frames: type|dir|ecu|id|channel · events: topic|type",
    ),
    from_: str | None = Query(None, alias="from", description="Epoch, ISO-8601 oder relativ (-5m)"),
    to: str | None = None,
    bucket_s: float | None = Query(None, gt=0),
    ecu: str | None = None,
    p: Platform = PlatformDep,
) -> dict[str, Any]:
    t_from, t_to = _window(from_, to)
    b = bucket_s or auto_bucket(t_to - t_from)
    if metric == "frames":
        items = frame_items(p.trace.frames, t_from, t_to)
        if ecu:
            items = [i for i in items if i.get("ecu") in (ecu, "*")]
    elif metric == "uds":
        items = p.history.query(t_from, t_to, {"uds"}, ecu, limit=1_000_000)
    else:
        items = p.history.query(t_from, t_to, None, ecu, limit=1_000_000)
    return {"metric": metric, **bucketize(items, t_from, t_to, b, group_by)}


@router.get(
    "/stats/summary",
    tags=["stats"],
    summary="Kennzahlen eines Zeitraums (UDS nach Typ/Service, NRCs, Latenz, Frames)",
)
async def stats_summary(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    ecu: str | None = None,
    bucket_s: float | None = None,
    p: Platform = PlatformDep,
) -> dict[str, Any]:
    t_from, t_to = _window(from_, to, "-15m")
    return {"from": t_from, "to": t_to, **p.reports.stats(t_from, t_to, ecu, bucket_s)}


@router.get(
    "/events",
    tags=["stats"],
    summary="Ereignis-Zeitleiste (UDS, Session, Security, Läufe, Fehler, Markierungen)",
)
async def events(
    from_: str | None = Query(None, alias="from"),
    to: str | None = None,
    topics: str | None = None,
    types: str | None = None,
    ecu: str | None = None,
    limit: int = Query(1000, le=100_000),
    p: Platform = PlatformDep,
) -> dict[str, Any]:
    t_from, t_to = _window(from_, to, "-1h")
    tp = set(filter(None, (topics or "").split(","))) or None
    ty = set(filter(None, (types or "").split(","))) or None
    items = p.history.query(t_from, t_to, tp, ecu, ty, limit)
    return {"from": t_from, "to": t_to, "items": items}


class MarkerIn(BaseModel):
    text: str
    color: str | None = None


@router.post("/events/marker", tags=["stats"], summary="Markierung in der Zeitleiste setzen")
async def marker(body: MarkerIn, p: Platform = PlatformDep) -> dict[str, Any]:
    e = p.history.marker(body.text, body.color)
    p.events.publish("marker.added", text=body.text, color=body.color)
    return e


# =============================================================================================
# Reports
# =============================================================================================


@router.get("/reports", tags=["reports"], summary="Manuelle Reports")
async def reports(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return p.reports.list_items()


@router.post(
    "/reports",
    tags=["reports"],
    summary="Report über einen Zeitbereich erstellen (Statistik, Ereignisse, Läufe, Traces, Logs)",
)
async def create_report(spec: ReportSpec, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.reports.create(spec)


@router.get(
    "/reports/{rid}", tags=["reports"], summary="Report als JSON, HTML oder ZIP (inkl. Trace-/Log-Anhänge)"
)
async def get_report(
    rid: str, format: Literal["json", "html", "zip"] = "json", p: Platform = PlatformDep
) -> Response:
    if format == "html":
        return HTMLResponse(p.reports.html(rid))
    if format == "zip":
        return Response(
            p.reports.zip(rid),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{rid}.zip"'},
        )
    return JSONResponse(p.reports.get(rid))


@router.get("/reports/{rid}/attachments/{name}", tags=["reports"], summary="Einzelnen Anhang laden")
async def report_attachment(rid: str, name: str, p: Platform = PlatformDep) -> FileResponse:
    return FileResponse(p.reports.attachment(rid, name), filename=name)


@router.delete("/reports/{rid}", tags=["reports"])
async def delete_report(rid: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.reports.delete(rid)
    return {"ok": True}


@router.get(
    "/runs/{run_id}/export",
    tags=["reports"],
    summary="Testlauf exportieren: HTML oder ZIP (JSON+JUnit+HTML+Traces+Logs)",
)
async def export_run(
    run_id: str,
    format: Literal["html", "zip"] = "zip",
    trace_formats: str = "asc,csv,jsonl",
    p: Platform = PlatformDep,
) -> Response:
    if format == "html":
        return HTMLResponse(
            p.reports.run_html(run_id), headers={"Content-Disposition": f'inline; filename="{run_id}.html"'}
        )
    data = p.reports.run_bundle(run_id, [f for f in trace_formats.split(",") if f])
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


# =============================================================================================
# Dashboards & Aktionen
# =============================================================================================


@router.get("/dashboards", tags=["dashboards"], summary="Dashboards (eigene + aus Konfig-Paketen)")
async def dashboards(p: Platform = PlatformDep) -> list[dict[str, Any]]:
    return p.dashboards.list_items()


@router.post("/dashboards", tags=["dashboards"], summary="Dashboard anlegen")
async def create_dashboard(d: Dashboard, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.dashboards.put(d, create=True).model_dump(mode="json")


@router.get("/dashboards/{did}", tags=["dashboards"])
async def get_dashboard(did: str, p: Platform = PlatformDep) -> dict[str, Any]:
    return p.dashboards.get(did)


@router.put("/dashboards/{did}", tags=["dashboards"], summary="Dashboard speichern (Layout, Panels, Knöpfe)")
async def put_dashboard(did: str, d: dict[str, Any] = Body(...), p: Platform = PlatformDep) -> dict[str, Any]:
    d["id"] = did
    return p.dashboards.put(Dashboard.model_validate(d), create=False).model_dump(mode="json")


@router.delete("/dashboards/{did}", tags=["dashboards"])
async def delete_dashboard(did: str, p: Platform = PlatformDep) -> dict[str, Any]:
    p.dashboards.delete(did)
    return {"ok": True}


@router.post(
    "/dashboards/{did}/panels/{pid}/buttons/{idx}/press",
    tags=["dashboards"],
    summary="Knopf eines Panels auslösen",
)
async def press(did: str, pid: str, idx: int, p: Platform = PlatformDep) -> dict[str, Any]:
    d = p.dashboards.get(did)
    panel = next((x for x in d["panels"] if x["id"] == pid), None)
    if panel is None or not 0 <= idx < len(panel.get("buttons", [])):
        raise NotFoundError("Panel/Knopf nicht gefunden")
    btn = panel["buttons"][idx]
    res = await run_action(p, Action.model_validate(btn["action"]))
    p.events.publish(
        "dashboard.action", dashboard=did, panel=pid, label=btn["label"], status=res.get("status")
    )
    return res


@router.post(
    "/actions/run", tags=["dashboards"], summary="Eine Aktion direkt ausführen (wie ein Dashboard-Knopf)"
)
async def action_run(a: Action, p: Platform = PlatformDep) -> dict[str, Any]:
    return await run_action(p, a)


# =============================================================================================
# Hilfe
# =============================================================================================


@router.get(
    "/help", tags=["help"], summary="Inhaltsverzeichnis der Hilfe (Kategorien, Themen, Kontext-Zuordnung)"
)
async def help_index(lang: str = "de") -> dict[str, Any]:
    from ..help.service import get_help

    return get_help(lang).index()


@router.get("/help/search", tags=["help"], summary="Hilfe durchsuchen (Treffer je Abschnitt mit Ausschnitt)")
async def help_search(
    q: str = Query(..., min_length=1), limit: int = Query(20, le=100), lang: str = "de"
) -> dict[str, Any]:
    from ..help.service import get_help

    return {"query": q, "results": get_help(lang).search(q, limit)}


@router.get(
    "/help/topics/{tid}",
    tags=["help"],
    summary="Hilfethema als Markdown mit Abschnitten und verwandten Themen",
)
async def help_topic(tid: str, lang: str = "de") -> dict[str, Any]:
    from ..help.service import get_help

    return get_help(lang).topic(tid)


@router.get(
    "/help/context/{ctx}", tags=["help"], summary="Kontexthilfe zu einer Ansicht (und optional einem Feld)"
)
async def help_context(ctx: str, field: str | None = None, lang: str = "de") -> dict[str, Any]:
    from ..help.service import get_help

    return get_help(lang).context(ctx, field)


@router.get(
    "/help/tooltips", tags=["help"], summary="Kurzerklärungen aller Felder (Schlüssel 'ansicht.feld')"
)
async def help_tooltips(lang: str = "de") -> dict[str, Any]:
    from ..help.service import get_help

    return get_help(lang).tooltips


# =============================================================================================
# KI-Assistent: Konfiguration aus Spezifikation
# =============================================================================================


@router.get(
    "/config/ai-prompt",
    tags=["config"],
    summary="Prompt für eine KI: Konfig-Paket aus einer Spezifikation erstellen",
)
async def ai_prompt(
    package_id: str = "",
    package_name: str = "",
    sections: str | None = Query(
        None,
        description="Kommagetrennt: isotp,ecus,security,dids,dtcs,routines,messages,sequences,tests,simulation",
    ),
    simulation: bool = False,
    tests: bool = True,
    notes: str = "",
    json_schema: bool = Query(False, description="Vollständiges JSON-Schema anhängen (lang)"),
    format: Literal["json", "text"] = "json",
) -> Any:
    from ..config.ai_prompt import SECTIONS_ALL, build_prompt

    secs = [s for s in (sections or "").split(",") if s] or list(SECTIONS_ALL)
    if simulation and "simulation" not in secs:
        secs.append("simulation")
    text = build_prompt(
        package_id=package_id,
        package_name=package_name,
        sections=secs,
        with_simulation=simulation,
        with_tests=tests,
        notes=notes,
        include_json_schema=json_schema,
    )
    if format == "text":
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")
    return {"prompt": text, "length": len(text), "sections": secs, "available_sections": SECTIONS_ALL}


class AiCheckIn(BaseModel):
    content: str
    do_import: bool = False
    activate: bool = True
    overwrite: bool = False


@router.post(
    "/config/ai-check",
    tags=["config"],
    summary="KI-Antwort prüfen (und importieren); bei Fehlern Korrektur-Prompt",
)
async def ai_check(body: AiCheckIn, p: Platform = PlatformDep) -> dict[str, Any]:
    import re

    from ..config.ai_prompt import build_fix_prompt, extract_yaml
    from ..config.loader import load_structured, package_hash, parse_package
    from ..core.errors import UdsBenchError

    yaml_text = extract_yaml(body.content)
    todos = [m.strip() for m in re.findall(r"#\s*((?:TODO|PRÜFEN|PRUEFEN)\b.*)$", yaml_text, re.M)]
    todos += sorted(set(re.findall(r"\bTODO_\w+", yaml_text)))
    # Abschnitt „Offene Punkte“ der KI-Antwort (außerhalb des YAML-Blocks) übernehmen
    m = re.search(
        r"#+\s*Offene Punkte\s*\n(.*?)(?:\n#+\s|\Z)", body.content.replace(yaml_text, ""), re.S | re.I
    )
    if m:
        todos += [
            ln.lstrip("-*• ").strip()
            for ln in m.group(1).splitlines()
            if ln.strip().startswith(("-", "*", "•"))
        ]
    try:
        pkg = parse_package(load_structured(yaml_text))
    except UdsBenchError as exc:
        details = _norm_errors(exc.details)
        return {
            "ok": False,
            "message": exc.message,
            "errors": details,
            "todos": todos,
            "fix_prompt": build_fix_prompt(yaml_text, details, exc.message),
        }
    summary = {
        "id": pkg.package.id,
        "name": pkg.package.name,
        "version": pkg.package.version,
        "hash": package_hash(pkg),
        "counts": {
            "isotp_profiles": len(pkg.isotp_profiles),
            "ecus": len(pkg.ecus),
            "security_providers": len(pkg.security_providers),
            "dids": len(pkg.catalogs.dids),
            "dtcs": len(pkg.catalogs.dtcs),
            "routines": len(pkg.catalogs.routines),
            "messages": len(pkg.messages),
            "sequences": len(pkg.sequences),
            "tests": len(pkg.tests),
            "testsuites": len(pkg.testsuites),
            "simulated_ecus": len(pkg.simulation.ecus),
        },
    }
    result: dict[str, Any] = {"ok": True, "package": summary, "todos": todos, "imported": False}
    if body.do_import:
        try:
            entry = p.packages.add(
                pkg.model_dump(mode="json", by_alias=True), overwrite=body.overwrite, activate=body.activate
            )
            await p.settle()
            result["imported"] = True
            result["package"]["active"] = entry.id in p.packages.active
        except UdsBenchError as exc:
            errs = _norm_errors(exc.details)
            result.update(
                {
                    "ok": False,
                    "imported": False,
                    "message": exc.message,
                    "errors": errs,
                    "fix_prompt": build_fix_prompt(yaml_text, errs, exc.message),
                }
            )
    return result


def _norm_errors(details: Any) -> list[dict[str, Any]]:
    """Fehlerdetails einheitlich als [{loc, msg, type}] (Validierung, Kollisionen, Querverweise)."""
    items = details if isinstance(details, list) else ([details] if details else [])
    out = []
    for d in items:
        if isinstance(d, dict):
            out.append(
                {
                    "loc": str(d.get("loc", "")),
                    "msg": str(d.get("msg", d)),
                    "type": str(d.get("type", "validation")),
                }
            )
        else:
            out.append({"loc": "", "msg": str(d), "type": "conflict"})
    return out
