"""Live-Trace: Klassifizierung, Ringpuffer, rekonstruierter Nachrichten-Trace, WebSocket-Verteilung."""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..can.frame import CanFrame
from ..core.hexutil import to_hex
from ..isotp.monitor import IsoTpMonitor
from ..uds.codec import classify_payload, describe_payload

if TYPE_CHECKING:
    from .platform import Platform


@dataclass
class TraceFilter:
    ids: set[int] | None = None
    direction: str | None = None  # "rx" | "tx"
    only_uds: bool = False
    services: set[int] | None = None
    data_contains: str | None = None
    channel: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TraceFilter:
        from .hexutil import parse_int

        def ints(v: Any) -> set[int] | None:
            if v in (None, "", []):
                return None
            if isinstance(v, str):
                v = [x for x in v.replace(",", " ").split() if x]
            return {parse_int(x) if not isinstance(x, int) else x for x in v}

        return cls(
            ids=ints(d.get("ids")),
            direction=d.get("direction") or None,
            only_uds=bool(d.get("only_uds")),
            services=ints(d.get("services")),
            data_contains=(str(d["data_contains"]).replace(" ", "").upper() or None)
            if d.get("data_contains")
            else None,
            channel=d.get("channel") or None,
        )

    def match(self, e: dict[str, Any]) -> bool:
        if self.channel and e.get("channel") != self.channel:
            return False
        if self.direction and e.get("dir") != self.direction:
            return False
        if self.ids is not None and e.get("id", e.get("can_id")) not in self.ids:
            return False
        if self.only_uds and not e.get("uds") and e.get("kind") != "message":
            return False
        if self.services is not None:
            sid = e.get("sid")
            if sid is None:
                return False
            base = sid - 0x40 if 0x50 <= sid <= 0xFE and sid != 0x7F else sid
            if sid == 0x7F:
                base = e.get("nrc_sid", -1)
            if base not in self.services and sid not in self.services:
                return False
        if self.data_contains and self.data_contains not in str(e.get("data", e.get("payload", ""))).replace(
            " ", ""
        ):
            return False
        return True


@dataclass
class TraceSubscriber:
    queue: asyncio.Queue[dict[str, Any]]
    filter: TraceFilter = field(default_factory=TraceFilter)
    paused: bool = False
    views: set[str] = field(default_factory=lambda: {"frames", "messages"})
    dropped: int = 0


class TraceService:
    def __init__(self, platform: Platform, buffer_size: int = 100_000) -> None:
        self.platform = platform
        self.frames: deque[dict[str, Any]] = deque(maxlen=buffer_size)
        self.messages: deque[dict[str, Any]] = deque(maxlen=max(1000, buffer_size // 4))
        self.monitor = IsoTpMonitor(self._on_message)
        self.subscribers: list[TraceSubscriber] = []
        self.bookmarks: list[dict[str, Any]] = []
        self._seq = itertools.count(1)
        self.t0: float | None = None
        self.frame_listeners: list[Any] = []

    def update_endpoints(self) -> None:
        merged = self.platform.packages.merged
        self.monitor.set_endpoints({eid: r.profile for eid, r in merged.ecus.items()})

    # ------------------------------------------------------------------------------------
    def on_frame(self, frame: CanFrame) -> None:
        if self.t0 is None:
            self.t0 = frame.timestamp
        d = frame.to_dict()
        d["seq"] = next(self._seq)
        d["kind"] = "frame"
        d["cid"] = None
        from .context import current

        d["cid"] = current()
        cls = self.monitor.classify_frame(frame)
        if cls:
            d["ecu"] = cls.get("ecu")
            d["role"] = cls.get("role")
            d["pci"] = cls.get("pci")
            if "isotp" in cls:
                d["isotp"] = cls["isotp"]
            payload = cls.get("payload")
            if payload is not None:
                d["uds"] = classify_payload(payload)
                d["sid"] = payload[0]
                if payload[0] == 0x7F and len(payload) > 1:
                    d["nrc_sid"] = payload[1]
                d["text"] = describe_payload(payload, self.platform.packages.merged.catalogs)
            elif cls.get("pci") == "FF" and "sid" in cls:
                d["uds"] = "segmented"
                d["sid"] = cls["sid"]
                d["text"] = f"First Frame ({cls['isotp'].get('length')} Byte)"
            elif cls.get("pci") == "CF":
                d["text"] = f"Consecutive Frame SN={cls['isotp'].get('seq')}"
            elif cls.get("pci") == "FC":
                iso = cls["isotp"]
                fs = {0: "CTS", 1: "WAIT", 2: "OVFLW"}.get(iso.get("flow_status"), "?")
                d["text"] = f"Flow Control {fs} BS={iso.get('bs')} STmin=0x{iso.get('st_min') or 0:02X}"
            if "error" in cls:
                d["text"] = cls["error"]
        else:
            dbc = self.platform.dbc.decode_frame(frame)
            if dbc is not None:
                d["dbc"] = dbc
                d["text"] = self.platform.dbc.describe(dbc)
        self.frames.append(d)
        self.monitor.feed(frame)
        self._fanout(d)
        for fn in self.frame_listeners:
            fn(frame)

    def _on_message(self, m: dict[str, Any]) -> None:
        payload = m.pop("payload_bytes", None)
        m["kind"] = "message"
        m["seq"] = next(self._seq)
        if payload is not None:
            m["payload"] = to_hex(payload)
            m["len"] = len(payload)
            m["uds"] = classify_payload(payload)
            m["sid"] = payload[0]
            if payload[0] == 0x7F and len(payload) > 1:
                m["nrc_sid"] = payload[1]
                m["nrc"] = payload[2] if len(payload) > 2 else None
            m["text"] = describe_payload(payload, self.platform.packages.merged.catalogs)
        m["id"] = m.get("can_id")
        self.messages.append(m)
        self._fanout(m)

    def _fanout(self, e: dict[str, Any]) -> None:
        view = "frames" if e["kind"] == "frame" else "messages"
        for sub in self.subscribers:
            if sub.paused or view not in sub.views or not sub.filter.match(e):
                continue
            try:
                sub.queue.put_nowait(e)
            except asyncio.QueueFull:
                sub.dropped += 1

    # ------------------------------------------------------------------------------------
    def subscribe(self, maxsize: int = 20000) -> TraceSubscriber:
        sub = TraceSubscriber(asyncio.Queue(maxsize))
        self.subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: TraceSubscriber) -> None:
        if sub in self.subscribers:
            self.subscribers.remove(sub)

    def query(
        self, view: str = "frames", since_seq: int = 0, limit: int = 1000, flt: TraceFilter | None = None
    ) -> list[dict[str, Any]]:
        src = self.frames if view == "frames" else self.messages
        out = [e for e in list(src) if e["seq"] > since_seq and (flt is None or flt.match(e))]
        return out[-limit:]

    def clear(self) -> None:
        self.frames.clear()
        self.messages.clear()
        self.bookmarks.clear()
        self.t0 = None

    def add_bookmark(self, seq: int, note: str) -> dict[str, Any]:
        bm = {"seq": seq, "note": note}
        self.bookmarks.append(bm)
        return bm
