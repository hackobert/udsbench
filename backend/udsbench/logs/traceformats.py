"""Trace-Formate: natives JSONL, CSV, ASC (ASCII-Logformat) und candump-Log (Linux can-utils)."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from collections.abc import Iterable
from typing import Any

from ..can.frame import CanFrame
from ..core.hexutil import parse_hex

FORMATS = ("jsonl", "csv", "asc", "candump")


def export_frames(frames: Iterable[CanFrame], fmt: str, meta: dict[str, Any] | None = None) -> str:
    frames = list(frames)
    t0 = frames[0].timestamp if frames else time.time()
    if fmt == "jsonl":
        lines = [
            json.dumps({"type": "header", "format": "udsbench-trace", "version": 1, "t0": t0, **(meta or {})})
        ]
        lines += [
            json.dumps({k: v for k, v in f.to_dict().items() if k not in ("ascii", "id_hex")}) for f in frames
        ]
        return "\n".join(lines) + "\n"
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            ["timestamp", "rel_time", "channel", "direction", "id", "extended", "fd", "brs", "dlc", "data"]
        )
        for f in frames:
            w.writerow(
                [
                    f"{f.timestamp:.6f}",
                    f"{f.timestamp - t0:.6f}",
                    f.channel,
                    f.direction,
                    f.id_str(),
                    int(f.is_extended_id),
                    int(f.is_fd),
                    int(f.bitrate_switch),
                    len(f.data),
                    f.data.hex(" ").upper(),
                ]
            )
        return buf.getvalue()
    if fmt == "asc":
        start = time.strftime("%a %b %d %I:%M:%S.000 %p %Y", time.localtime(t0))
        out = [
            f"date {start}",
            "base hex  timestamps absolute",
            "internal events logged",
            "Begin Triggerblock " + start,
        ]
        chmap: dict[str, int] = {}
        for f in frames:
            ch = chmap.setdefault(f.channel, len(chmap) + 1)
            rel = f.timestamp - t0
            cid = f"{f.arbitration_id:X}" + ("x" if f.is_extended_id else "")
            dirn = "Tx" if f.direction == "tx" else "Rx"
            if f.is_fd:
                flags = f"{int(f.bitrate_switch)} 0"
                out.append(
                    f"{rel:>11.6f} CANFD {ch:>3} {dirn} {cid:>8} {'':>32} {flags} {f.dlc:x} {len(f.data):>2} {f.data.hex(' ').upper()}"
                )
            else:
                out.append(
                    f"{rel:>11.6f} {ch:<2} {cid:<15} {dirn}   d {len(f.data)} {f.data.hex(' ').upper()}"
                )
        out.append("End TriggerBlock")
        return "\n".join(out) + "\n"
    if fmt == "candump":
        out = []
        for f in frames:
            cid = f"{f.arbitration_id:08X}" if f.is_extended_id else f"{f.arbitration_id:03X}"
            sep = "##" + ("1" if f.bitrate_switch else "0") if f.is_fd else "#"
            out.append(
                f"({f.timestamp:.6f}) {f.channel} {cid}{sep}{f.data.hex().upper()}"
                + (" T" if f.direction == "tx" else " R")
            )
        return "\n".join(out) + "\n"
    raise ValueError(f"Unbekanntes Format {fmt!r} (verfügbar: {', '.join(FORMATS)})")


_ASC_CLASSIC = re.compile(
    r"^\s*(?P<t>\d+\.\d+)\s+(?P<ch>\d+)\s+(?P<id>[0-9A-Fa-f]+)(?P<x>x?)\s+(?P<dir>Rx|Tx)\s+d\s+(?P<dlc>[0-9A-Fa-f]+)\s*(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)"
)
_ASC_FD = re.compile(
    r"^\s*(?P<t>\d+\.\d+)\s+CANFD\s+(?P<ch>\d+)\s+(?P<dir>Rx|Tx)\s+(?P<id>[0-9A-Fa-f]+)(?P<x>x?)\s+(?:\S+\s+)?(?P<brs>[01])\s+(?P<esi>[01])\s+(?P<dlc>[0-9A-Fa-f]+)\s+(?P<len>\d+)\s*(?P<data>(?:[0-9A-Fa-f]{2}\s*)*)"
)
_CANDUMP = re.compile(
    r"^\((?P<t>[\d.]+)\)\s+(?P<ch>\S+)\s+(?P<id>[0-9A-Fa-f]+)(?P<sep>##(?P<flags>[0-9A-Fa-f])|#)(?P<data>[0-9A-Fa-f]*)\s*(?P<dir>[TR])?"
)


def detect_format(text: str, filename: str = "") -> str:
    fn = filename.lower()
    for f in FORMATS:
        if fn.endswith("." + f) or (f == "candump" and fn.endswith(".log")):
            return f
    head = text.lstrip()[:200]
    if head.startswith("{"):
        return "jsonl"
    if head.lower().startswith("timestamp,"):
        return "csv"
    if head.startswith("date") or "Begin Triggerblock" in text[:500]:
        return "asc"
    if head.startswith("("):
        return "candump"
    raise ValueError("Trace-Format nicht erkannt")


def import_frames(
    text: str, fmt: str | None = None, filename: str = ""
) -> tuple[list[CanFrame], dict[str, Any]]:
    fmt = fmt or detect_format(text, filename)
    frames: list[CanFrame] = []
    meta: dict[str, Any] = {"format": fmt}
    if fmt == "jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("type") == "header":
                meta.update(d)
                continue
            frames.append(CanFrame.from_dict(d))
    elif fmt == "csv":
        for row in csv.DictReader(io.StringIO(text)):
            frames.append(
                CanFrame(
                    int(row["id"], 16),
                    parse_hex(row.get("data", "")),
                    bool(int(row.get("extended", 0) or 0)),
                    bool(int(row.get("fd", 0) or 0)),
                    bool(int(row.get("brs", 0) or 0)),
                    timestamp=float(row["timestamp"]),
                    direction=row.get("direction", "rx") or "rx",
                    channel=row.get("channel", "default") or "default",
                )
            )
    elif fmt == "asc":
        base = time.time()
        for line in text.splitlines():
            m = _ASC_FD.match(line) or _ASC_CLASSIC.match(line)
            if not m:
                continue
            g = m.groupdict()
            fd = "len" in g and g.get("len") is not None
            data = parse_hex(g["data"] or "")
            frames.append(
                CanFrame(
                    int(g["id"], 16),
                    data,
                    bool(g["x"]),
                    fd,
                    bool(int(g.get("brs") or 0)) if fd else False,
                    timestamp=base + float(g["t"]),
                    direction="tx" if g["dir"] == "Tx" else "rx",
                    channel=f"ch{g['ch']}",
                )
            )
    elif fmt == "candump":
        for line in text.splitlines():
            m = _CANDUMP.match(line.strip())
            if not m:
                continue
            g = m.groupdict()
            fd = g["sep"].startswith("##")
            frames.append(
                CanFrame(
                    int(g["id"], 16),
                    parse_hex(g["data"]),
                    len(g["id"]) > 3,
                    fd,
                    bool(int(g["flags"] or "0", 16) & 1) if fd else False,
                    timestamp=float(g["t"]),
                    direction="tx" if g.get("dir") == "T" else "rx",
                    channel=g["ch"],
                )
            )
    else:
        raise ValueError(f"Unbekanntes Format {fmt!r}")
    return frames, meta
