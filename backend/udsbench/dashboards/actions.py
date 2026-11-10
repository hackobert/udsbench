"""Ausführung von Dashboard-Aktionen (Knöpfe) – dieselben Operationen wie die REST-API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..can.frame import CanFrame
from ..core.context import correlated, new_id
from ..core.errors import ValidationFailed
from ..core.hexutil import parse_int, to_hex
from ..messages.engine import Engine, ExecContext
from ..messages.expr import render_payload
from ..messages.models import Step
from .models import Action

if TYPE_CHECKING:
    from ..core.platform import Platform


async def _step(p: Platform, step: dict[str, Any], ecu: str | None, vars: dict[str, Any]) -> dict[str, Any]:
    ctx = ExecContext(p, vars=dict(vars), ecu=ecu)
    await Engine(p).run_step(Step.model_validate(step), ctx)
    rec = ctx.records[-1]
    res = ctx.last
    # Für Knöpfe zählt die Antwort: negative Antwort oder Fehler = nicht erfolgreich
    outcome = "none"
    if res is not None:
        if res.positive:
            outcome = "positive"
        elif res.negative:
            outcome = "negative"
        elif res.suppress_positive and not res.error:
            outcome = "suppressed"
        else:
            outcome = "error"
    status = rec.status
    if status == "passed" and outcome in ("negative", "error"):
        status = "failed"
    return {
        "status": status,
        "outcome": outcome,
        "step": rec.to_dict(),
        "result": res.to_dict() if res else None,
    }


async def run_action(p: Platform, a: Action) -> dict[str, Any]:
    with correlated(new_id("act_")) as cid:
        out = await _run(p, a)
    out["cid"] = cid
    return out


async def _run(p: Platform, a: Action) -> dict[str, Any]:
    t = a.type
    if t == "message":
        return await _step(
            p,
            {
                "send": {
                    "message": str(a.ref),
                    "vars": a.vars,
                    **({"functional": True} if a.functional else {}),
                }
            },
            a.ecu
            or (
                p.packages.merged.messages[str(a.ref)].ecu
                if str(a.ref) in p.packages.merged.messages
                else None
            ),
            {},
        )
    if t == "uds":
        return await _step(
            p, {"send": {"payload": a.payload, "functional": a.functional, "vars": a.vars}}, a.ecu, {}
        )
    if t == "step":
        return await _step(p, a.step or {}, a.ecu, a.vars)
    if t == "unlock":
        return await _step(p, {"unlock": parse_int(a.ref)}, a.ecu, {})
    if t == "session":
        ref = a.ref
        return await _step(
            p,
            {
                "session": ref
                if isinstance(ref, int)
                else (parse_int(ref) if str(ref)[:2].lower() == "0x" or str(ref).isdigit() else ref)
            },
            a.ecu,
            {},
        )
    if t == "raw":
        data = render_payload(a.payload or "", dict(a.vars))
        if len(data) > 64:
            raise ValidationFailed("Zu viele Datenbytes")
        cid = parse_int(a.can_id)
        f = await p.connections.get(a.channel).send(CanFrame(cid, data, cid > 0x7FF, len(data) > 8))
        return {"status": "passed", "frame": f.to_dict()}
    if t in ("sequence", "test", "suite"):
        starter = {
            "sequence": p.runner.start_sequence,
            "test": p.runner.start_test,
            "suite": p.runner.start_suite,
        }[t]
        run = starter(str(a.ref), a.vars, a.ecu)
        return {"status": "started", "run_id": run.id, "run": run.to_dict(detail=False)}
    if t == "marker":
        e = p.history.marker(str(a.ref or a.payload or "Markierung"))
        p.events.publish("marker", text=e["text"])
        return {"status": "passed", "marker": e}
    if t == "record_start":
        return {"status": "passed", "recording": p.recorder.start(str(a.ref) if a.ref else None)}
    if t == "record_stop":
        return {"status": "passed", "recording": p.recorder.stop()}
    if t == "report":
        from ..reports.service import ReportSpec

        return {"status": "passed", "report": p.reports.create(ReportSpec.model_validate(a.report or {}))}
    raise ValidationFailed(f"Unbekannte Aktion {t!r}")  # pragma: no cover


__all__ = ["run_action", "to_hex"]
