"""Ereignis-Historie: zeitgestempelte Ereignisse (UDS, Session, Security, Läufe, Fehler …).

Grundlage für die Timechart (Statistik je Zeit-Bucket), die Ereignis-Zeitleiste und manuelle
Reports über einen Zeitbereich. Ereignisse liegen im Speicher (Ringpuffer) und werden zusätzlich
tageweise als JSON-Lines im Datenverzeichnis abgelegt, damit Reports auch nach einem Neustart
frühere Zeitbereiche abdecken.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import Counter, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..uds.services import service_name

log = logging.getLogger("udsbench.app.history")

RECORDED_TOPICS = {
    "uds",
    "session",
    "security",
    "run",
    "connection",
    "isotp",
    "log",
    "recording",
    "replay",
    "simulation",
    "packages",
    "marker",
}


def summarize(evt: dict[str, Any]) -> dict[str, Any] | None:
    """Reduziert ein Bus-Ereignis auf einen kompakten Historien-Eintrag (oder None = nicht speichern)."""
    topic = evt.get("topic")
    if topic not in RECORDED_TOPICS:
        return None
    base: dict[str, Any] = {"ts": evt.get("ts", time.time()), "topic": topic}
    if topic == "uds":
        r = evt.get("result") or {}
        req = (r.get("request") or "").split()
        sid = int(req[0], 16) if req else None
        if r.get("negative"):
            kind = "negative"
        elif r.get("positive"):
            kind = "positive"
        elif r.get("suppress_positive") and not r.get("error"):
            kind = "suppressed"
        elif r.get("error_kind") == "timeout":
            kind = "timeout"
        else:
            kind = "error"
        base.update(
            {
                "ecu": r.get("ecu"),
                "sid": sid,
                "service": service_name(sid) if sid is not None else None,
                "type": kind,
                "nrc": r.get("nrc"),
                "nrc_name": r.get("nrc_name"),
                "elapsed_ms": r.get("elapsed_ms"),
                "pending": r.get("pending_count", 0),
                "functional": r.get("functional"),
                "cid": r.get("cid"),
                "request": " ".join(req[:8]) + (" …" if len(req) > 8 else ""),
                "responses": len(r.get("responses") or []),
            }
        )
        return base
    if topic == "run":
        if evt.get("state") not in ("started", "finished", "queued"):
            return None
        base.update(
            {k: evt.get(k) for k in ("run_id", "state", "status", "kind", "target", "name", "summary")}
        )
        base["type"] = evt.get("state")
        return base
    if topic == "log":
        entry = evt.get("entry") or {}
        if entry.get("level") not in ("WARNING", "ERROR", "CRITICAL"):
            return None
        base.update(
            {
                "type": entry.get("level", "").lower(),
                "channel": entry.get("channel"),
                "msg": entry.get("msg"),
                "cid": entry.get("cid"),
            }
        )
        return base
    if topic == "isotp":
        if not str(evt.get("kind", "")).startswith("error"):
            return None
        base.update(
            {
                "type": evt.get("kind"),
                "transport": evt.get("transport"),
                "detail": {k: v for k, v in evt.items() if k not in ("topic", "ts", "kind", "transport")},
            }
        )
        return base
    if topic == "connection":
        base.update({"type": evt.get("state"), "channel": evt.get("channel")})
        return base
    extra = {
        k: v
        for k, v in evt.items()
        if k not in ("topic", "ts") and isinstance(v, (str, int, float, bool, type(None), list))
    }
    base.update(extra)
    base.setdefault("type", evt.get("state") or topic)
    return base


class HistoryStore:
    def __init__(self, directory: Path | None, maxlen: int = 200_000) -> None:
        self.dir = directory
        self.events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._fh: Any = None
        self._day = ""

    # Schreiben --------------------------------------------------------------------------
    def sink(self, evt: dict[str, Any]) -> None:
        e = summarize(evt)
        if e is not None:
            self.add(e)

    def add(self, e: dict[str, Any]) -> None:
        self.events.append(e)
        if self.dir is None:
            return
        day = time.strftime("%Y-%m-%d", time.localtime(e["ts"]))
        try:
            if day != self._day or self._fh is None:
                if self._fh:
                    self._fh.close()
                self.dir.mkdir(parents=True, exist_ok=True)
                self._fh = (self.dir / f"events-{day}.jsonl").open("a", encoding="utf-8")
                self._day = day
            self._fh.write(json.dumps(e, default=str, ensure_ascii=False) + "\n")
            self._fh.flush()
        except OSError as exc:  # pragma: no cover
            log.warning("Historie konnte nicht geschrieben werden: %s", exc)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def marker(self, text: str, color: str | None = None) -> dict[str, Any]:
        e = {"ts": time.time(), "topic": "marker", "type": "marker", "text": text, "color": color}
        self.add(e)
        return e

    # Lesen ------------------------------------------------------------------------------
    def _from_files(self, t_from: float, t_to: float) -> Iterable[dict[str, Any]]:
        if self.dir is None or not self.dir.is_dir():
            return []
        out: list[dict[str, Any]] = []
        day = t_from
        days: set[str] = set()
        while day <= t_to + 86400:
            days.add(time.strftime("%Y-%m-%d", time.localtime(day)))
            day += 86400
        for d in sorted(days):
            f = self.dir / f"events-{d}.jsonl"
            if not f.exists():
                continue
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if t_from <= e.get("ts", 0) <= t_to:
                        out.append(e)
        return out

    def query(
        self,
        t_from: float | None = None,
        t_to: float | None = None,
        topics: set[str] | None = None,
        ecu: str | None = None,
        types: set[str] | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        t_to = t_to or time.time()
        t_from = t_from if t_from is not None else t_to - 3600
        oldest_mem = self.events[0]["ts"] if self.events else time.time()
        src: Iterable[dict[str, Any]]
        src = (
            self._from_files(t_from, t_to)
            if t_from < oldest_mem and self.dir is not None
            else list(self.events)
        )
        out = []
        for e in src:
            if not t_from <= e["ts"] <= t_to:
                continue
            if topics and e["topic"] not in topics:
                continue
            if ecu and e.get("ecu") not in (None, ecu):
                continue
            if types and e.get("type") not in types:
                continue
            out.append(e)
        return out[-limit:]


def bucketize(
    items: list[dict[str, Any]], t_from: float, t_to: float, bucket_s: float, key: str
) -> dict[str, Any]:
    """Zählt Einträge je Zeit-Bucket und Gruppe (Wert des Feldes ``key``)."""
    bucket_s = max(bucket_s, 0.001)
    n = max(1, min(5000, math.ceil((t_to - t_from) / bucket_s)))
    groups: Counter[str] = Counter()
    buckets: list[dict[str, Any]] = [{"t": t_from + i * bucket_s, "counts": {}} for i in range(n)]
    lat: list[list[float]] = [[] for _ in range(n)]
    for it in items:
        idx = int((it["ts"] - t_from) // bucket_s)
        if not 0 <= idx < n:
            continue
        g = str(it.get(key) if it.get(key) is not None else "–")
        c = buckets[idx]["counts"]
        c[g] = c.get(g, 0) + 1
        groups[g] += 1
        if isinstance(it.get("elapsed_ms"), (int, float)):
            lat[idx].append(float(it["elapsed_ms"]))
    for i, b in enumerate(buckets):
        b["total"] = sum(b["counts"].values())
        if lat[i]:
            b["latency_avg_ms"] = round(sum(lat[i]) / len(lat[i]), 3)
            b["latency_max_ms"] = round(max(lat[i]), 3)
    return {
        "from": t_from,
        "to": t_to,
        "bucket_s": bucket_s,
        "group_by": key,
        "groups": dict(groups.most_common()),
        "total": sum(groups.values()),
        "buckets": buckets,
    }


def frame_items(frames: Iterable[dict[str, Any]], t_from: float, t_to: float) -> list[dict[str, Any]]:
    """Trace-Frames als zählbare Einträge (Typ: request/positive/negative/FF/CF/FC/can)."""
    out = []
    for f in frames:
        ts = f.get("ts", 0)
        if not t_from <= ts <= t_to:
            continue
        kind = f.get("uds") or f.get("pci") or "can"
        if kind == "segmented":
            kind = "FF"
        out.append(
            {
                "ts": ts,
                "type": kind,
                "dir": f.get("dir"),
                "ecu": f.get("ecu"),
                "id": f.get("id_hex"),
                "channel": f.get("channel"),
            }
        )
    return out
