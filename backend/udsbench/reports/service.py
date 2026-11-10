"""Reports: Export von Testläufen (JSON/JUnit/HTML/ZIP) und manuelle Reports über einen Zeitbereich.

Ein manueller Report bündelt für einen Zeitraum: Statistik (UDS nach Typ/Service, NRCs,
Antwortzeiten, Frames), Ereignis-Zeitleiste, Testläufe, rekonstruierten UDS-Trace, Logs und als
Anhänge die rohen Traces (ASC/CSV/candump/JSONL). Abgelegt unter ``<reports_dir>/manual/<id>/``.
"""

from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from ..can.frame import CanFrame
from ..config.loader import safe_name
from ..core.context import new_id
from ..core.errors import NotFoundError, ValidationFailed
from ..core.history import bucketize, frame_items
from ..logs.traceformats import FORMATS, export_frames
from ..testrunner.report import to_junit
from .html import render_manual, render_run

if TYPE_CHECKING:
    from ..core.platform import Platform


def parse_time(v: Any, now: float | None = None) -> float:
    """Epoch-Sekunden, ISO-8601 (lokal, falls ohne Zone) oder relativ ("-15m", "-2h", "-30s", "now")."""
    now = now or time.time()
    if v is None or v == "" or v == "now":
        return now
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.startswith("-") and s[-1] in "smhd":
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[s[-1]]
        return now - float(s[1:-1]) * mult
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ValidationFailed(f"Ungültige Zeitangabe {v!r}") from exc


class ReportInclude(BaseModel):
    stats: bool = True
    events: bool = True
    runs: bool = True
    messages: bool = True
    frames: bool = True
    logs: bool = True
    recordings: bool = Field(True, description="Frames aus gespeicherten Aufzeichnungen im Zeitraum ergänzen")


class ReportSpec(BaseModel):
    title: str = "Diagnose-Report"
    from_: Any = Field("-15m", alias="from", description="Epoch, ISO-8601 oder relativ (-15m)")
    to: Any = Field("now")
    ecu: str | None = None
    notes: str = ""
    author: str = ""
    bucket_s: float | None = Field(None, description="Bucketgröße der Diagramme (Default automatisch)")
    include: ReportInclude = Field(default_factory=ReportInclude)
    trace_formats: list[Literal["asc", "csv", "candump", "jsonl"]] = Field(
        default_factory=lambda: ["asc", "csv"]
    )
    run_ids: list[str] | None = Field(None, description="Nur diese Läufe (sonst alle im Zeitraum)")

    model_config = {"populate_by_name": True}


def auto_bucket(span: float) -> float:
    for b in (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600):
        if span / b <= 240:
            return b
    return 7200


class ReportService:
    def __init__(self, platform: Platform, directory: Path) -> None:
        self.platform = platform
        self.dir = directory / "manual"

    # ------------------------------------------------------------------------------------
    # Datensammlung
    # ------------------------------------------------------------------------------------
    def collect_frames(self, t_from: float, t_to: float, include_recordings: bool = True) -> list[CanFrame]:
        frames = [CanFrame.from_dict(d) for d in self.platform.trace.frames if t_from <= d["ts"] <= t_to]
        if include_recordings and (not frames or frames[0].timestamp > t_from):
            oldest = frames[0].timestamp if frames else t_to
            for rec in self.platform.recorder.list_items():
                if rec.get("recording"):
                    continue
                try:
                    rf, _ = self.platform.recorder.load(rec["id"])
                except Exception:
                    continue
                frames += [f for f in rf if t_from <= f.timestamp <= min(t_to, oldest)]
            frames.sort(key=lambda f: f.timestamp)
        return frames

    def collect_logs(self, t_from: float, t_to: float, cid: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        log_dir = self.platform.log_dir
        if log_dir.is_dir():
            for f in sorted(log_dir.glob("*.jsonl*")):
                try:
                    with f.open(encoding="utf-8") as fh:
                        for line in fh:
                            try:
                                d = json.loads(line)
                            except ValueError:
                                continue
                            if t_from <= d.get("ts", 0) <= t_to and (cid is None or d.get("cid") == cid):
                                out.append(d)
                except OSError:
                    continue
        if not out:  # z. B. ohne Dateilogging: Ringpuffer
            from ..logs.setup import get_buffer

            out = [d for d in get_buffer().query(limit=100_000, cid=cid) if t_from <= d["ts"] <= t_to]
        out.sort(key=lambda d: d.get("ts", 0))
        return out[-50_000:]

    def stats(
        self,
        t_from: float,
        t_to: float,
        ecu: str | None = None,
        bucket_s: float | None = None,
        frames: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        b = bucket_s or auto_bucket(t_to - t_from)
        uds = self.platform.history.query(t_from, t_to, {"uds"}, ecu, limit=1_000_000)
        lat = [x["elapsed_ms"] for x in uds if isinstance(x.get("elapsed_ms"), (int, float))]
        fr = frame_items(frames if frames is not None else list(self.platform.trace.frames), t_from, t_to)
        if ecu:
            fr = [f for f in fr if f.get("ecu") in (ecu, "*")]
        logs = self.platform.history.query(t_from, t_to, {"log"}, limit=1_000_000)
        return {
            "bucket_s": b,
            "uds_requests": len(uds),
            "uds_totals": dict(Counter(x["type"] for x in uds)),
            "services": dict(Counter(x.get("service") or "?" for x in uds).most_common()),
            "nrc_counts": dict(
                Counter(
                    f"0x{x['nrc']:02X} {x.get('nrc_name') or ''}".strip()
                    for x in uds
                    if x.get("nrc") is not None
                ).most_common()
            ),
            "ecus": dict(Counter(x.get("ecu") or "?" for x in uds).most_common()),
            "latency": {
                "avg": round(sum(lat) / len(lat), 3),
                "min": min(lat),
                "max": max(lat),
                "count": len(lat),
            }
            if lat
            else None,
            "frames": len(fr),
            "log_problems": len(logs),
            "uds_by_type": bucketize(uds, t_from, t_to, b, "type"),
            "uds_by_service": bucketize(uds, t_from, t_to, b, "service"),
            "frames_by_type": bucketize(fr, t_from, t_to, b, "type"),
        }

    def _runs(self, t_from: float, t_to: float, run_ids: list[str] | None) -> list[dict[str, Any]]:
        out = []
        for r in self.platform.runner.list_items():
            if run_ids is not None:
                if r["run_id"] not in run_ids:
                    continue
            else:
                start = r.get("started") or r.get("created") or 0
                end = r.get("finished") or time.time()
                if end < t_from or start > t_to:
                    continue
            try:
                out.append(self.platform.runner.get(r["run_id"]).to_dict())
            except NotFoundError:
                continue
        return sorted(out, key=lambda d: d.get("created") or 0)

    # ------------------------------------------------------------------------------------
    # Manuelle Reports
    # ------------------------------------------------------------------------------------
    def create(self, spec: ReportSpec) -> dict[str, Any]:
        now = time.time()
        t_to = parse_time(spec.to, now)
        t_from = parse_time(spec.from_, now)
        if t_from >= t_to:
            raise ValidationFailed("'from' muss vor 'to' liegen")
        if t_to - t_from > 31 * 86400:
            raise ValidationFailed("Zeitraum darf höchstens 31 Tage umfassen")
        inc = spec.include
        rid = new_id("rep_")
        folder = self.dir / rid
        folder.mkdir(parents=True, exist_ok=True)
        frames = self.collect_frames(t_from, t_to, inc.recordings) if (inc.frames or inc.stats) else []
        frame_dicts = [f.to_dict() for f in frames]
        # Klassifizierung aus dem Live-Puffer übernehmen (Aufzeichnungen sind unklassifiziert)
        live = {
            (d["ts"], d["id"], d["data"]): d for d in self.platform.trace.frames if t_from <= d["ts"] <= t_to
        }
        frame_dicts = [live.get((d["ts"], d["id"], d["data"]), d) for d in frame_dicts]
        rep: dict[str, Any] = {
            "id": rid,
            "title": spec.title,
            "created": now,
            "from": t_from,
            "to": t_to,
            "ecu": spec.ecu,
            "notes": spec.notes,
            "author": spec.author,
            "environment": self.platform.runner._environment(),
        }
        if inc.stats:
            rep["stats"] = self.stats(t_from, t_to, spec.ecu, spec.bucket_s, frame_dicts)
        if inc.events:
            rep["events"] = self.platform.history.query(t_from, t_to, None, spec.ecu, limit=100_000)
        if inc.runs:
            rep["runs"] = self._runs(t_from, t_to, spec.run_ids)
        if inc.messages:
            rep["messages"] = [
                m
                for m in self.platform.trace.messages
                if t_from <= m["ts"] <= t_to and (not spec.ecu or m.get("ecu") in (spec.ecu, "*"))
            ]
        attachments: list[dict[str, Any]] = []

        def attach(name: str, text: str, description: str) -> None:
            (folder / name).write_text(text, encoding="utf-8")
            attachments.append(
                {"name": name, "description": description, "size": (folder / name).stat().st_size}
            )

        if inc.frames and frames:
            for fmt in spec.trace_formats:
                attach(
                    f"trace.{fmt}",
                    export_frames(frames, fmt, {"report": rid}),
                    f"CAN-Trace ({fmt}, {len(frames)} Frames)",
                )
        if inc.messages and rep.get("messages"):
            lines = ["timestamp,channel,ecu,role,direction,can_id,length,payload,interpretation"]
            for m in rep["messages"]:
                lines.append(
                    ",".join(
                        [
                            '"' + str(x).replace('"', "'") + '"'
                            for x in (
                                f"{m['ts']:.6f}",
                                m.get("channel"),
                                m.get("ecu"),
                                m.get("role"),
                                m.get("dir"),
                                m.get("can_id"),
                                m.get("len"),
                                m.get("payload"),
                                m.get("text"),
                            )
                        ]
                    )
                )
            attach("uds_messages.csv", "\n".join(lines) + "\n", "Rekonstruierte UDS-Nachrichten (CSV)")
        if inc.logs:
            logs = self.collect_logs(t_from, t_to)
            rep["log_count"] = len(logs)
            if logs:
                attach(
                    "logs.jsonl",
                    "\n".join(json.dumps(d, default=str, ensure_ascii=False) for d in logs) + "\n",
                    f"Logs aller Kanäle ({len(logs)} Einträge, maskiert)",
                )
        if rep.get("events"):
            attach(
                "events.jsonl",
                "\n".join(json.dumps(d, default=str, ensure_ascii=False) for d in rep["events"]) + "\n",
                "Ereignis-Zeitleiste",
            )
        for run in rep.get("runs") or []:
            attach(f"run_{run['run_id']}.junit.xml", to_junit(run), f"JUnit-Report {run.get('name')}")
        rep["attachments"] = attachments
        (folder / "report.json").write_text(
            json.dumps(rep, default=str, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (folder / "report.html").write_text(render_manual(rep), encoding="utf-8")
        self.platform.history.marker(f"Report erstellt: {spec.title}")
        return self.summary(rep)

    @staticmethod
    def summary(rep: dict[str, Any]) -> dict[str, Any]:
        st = rep.get("stats") or {}
        return {
            "id": rep["id"],
            "title": rep.get("title"),
            "created": rep.get("created"),
            "from": rep.get("from"),
            "to": rep.get("to"),
            "ecu": rep.get("ecu"),
            "uds_requests": st.get("uds_requests"),
            "uds_totals": st.get("uds_totals"),
            "frames": st.get("frames"),
            "runs": len(rep.get("runs") or []),
            "attachments": rep.get("attachments", []),
        }

    def _folder(self, rid: str) -> Path:
        f = self.dir / safe_name(rid)
        if not (f / "report.json").exists():
            raise NotFoundError(f"Report {rid!r} nicht gefunden")
        return f

    def list_items(self) -> list[dict[str, Any]]:
        out = []
        if self.dir.is_dir():
            for f in self.dir.iterdir():
                try:
                    out.append(self.summary(json.loads((f / "report.json").read_text(encoding="utf-8"))))
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(out, key=lambda d: d.get("created") or 0, reverse=True)

    def get(self, rid: str) -> dict[str, Any]:
        return json.loads((self._folder(rid) / "report.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def html(self, rid: str) -> str:
        return (self._folder(rid) / "report.html").read_text(encoding="utf-8")

    def zip(self, rid: str) -> bytes:
        folder = self._folder(rid)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(folder.iterdir()):
                z.write(f, f"{rid}/{f.name}")
        return buf.getvalue()

    def attachment(self, rid: str, name: str) -> Path:
        p = self._folder(rid) / safe_name(name)
        if not p.is_file():
            raise NotFoundError(f"Anhang {name!r} nicht gefunden")
        return p

    def delete(self, rid: str) -> None:
        shutil.rmtree(self._folder(rid))

    # ------------------------------------------------------------------------------------
    # Export eines Testlaufs (inkl. angehängter Traces/Logs des Laufzeitraums)
    # ------------------------------------------------------------------------------------
    def run_html(self, run_id: str) -> str:
        return render_run(self.platform.runner.get(run_id).to_dict())

    def run_bundle(self, run_id: str, trace_formats: list[str] | None = None) -> bytes:
        run = self.platform.runner.get(run_id).to_dict()
        t_from = (run.get("started") or run.get("created") or time.time()) - 0.5
        t_to = (run.get("finished") or time.time()) + 0.5
        frames = self.collect_frames(t_from, t_to)
        logs = self.collect_logs(t_from, t_to, cid=run_id)
        events = self.platform.history.query(t_from, t_to, limit=100_000)
        buf = io.BytesIO()
        base = safe_name(run_id)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{base}/report.json", json.dumps(run, default=str, ensure_ascii=False, indent=1))
            z.writestr(f"{base}/report.junit.xml", to_junit(run))
            z.writestr(f"{base}/report.html", render_run(run))
            for fmt in trace_formats or ["asc", "csv", "jsonl"]:
                if fmt in FORMATS and frames:
                    z.writestr(f"{base}/trace.{fmt}", export_frames(frames, fmt, {"run_id": run_id}))
            z.writestr(
                f"{base}/logs.jsonl",
                "\n".join(json.dumps(d, default=str, ensure_ascii=False) for d in logs) + "\n",
            )
            z.writestr(
                f"{base}/events.jsonl",
                "\n".join(json.dumps(d, default=str, ensure_ascii=False) for d in events) + "\n",
            )
        return buf.getvalue()
