"""Passive ISO-TP-Rekonstruktion für den Nachrichten-Trace (sendet nie selbst)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..can.frame import CanFrame
from .codec import PCI_NAMES, IsoTpError, PciType, parse_frame
from .profile import IsoTpProfile


@dataclass
class EndpointMatch:
    profile: IsoTpProfile
    ecu: str
    role: str  # "request" | "response" | "functional"


@dataclass
class _Partial:
    expected: int
    data: bytearray
    seq: int
    t_first: float
    frames: int
    match: EndpointMatch
    direction: str
    raw_frames: list[str] = field(default_factory=list)


class IsoTpMonitor:
    def __init__(self, on_message: Callable[[dict[str, Any]], None]) -> None:
        self.on_message = on_message
        self._endpoints: dict[tuple[str, int, bool], EndpointMatch] = {}
        self._partials: dict[tuple[str, int, bool], _Partial] = {}

    def set_endpoints(self, ecus: dict[str, IsoTpProfile]) -> None:
        eps: dict[tuple[str, int, bool], EndpointMatch] = {}
        for ecu, p in ecus.items():
            eps[(p.channel, p.tx_id, p.extended_id)] = EndpointMatch(p, ecu, "request")
            eps[(p.channel, p.rx_id, p.extended_id)] = EndpointMatch(p, ecu, "response")
            if p.functional_id is not None:
                eps.setdefault(
                    (p.channel, p.functional_id, p.extended_id), EndpointMatch(p, "*", "functional")
                )
        self._endpoints = eps
        self._partials.clear()

    def match(self, frame: CanFrame) -> EndpointMatch | None:
        return self._endpoints.get((frame.channel, frame.arbitration_id, frame.is_extended_id))

    def classify_frame(self, frame: CanFrame) -> dict[str, Any] | None:
        m = self.match(frame)
        if not m:
            return None
        try:
            info = parse_frame(frame.data, m.profile.addressing)
        except IsoTpError as exc:
            return {"ecu": m.ecu, "role": m.role, "pci": "?", "error": str(exc)}
        d: dict[str, Any] = {
            "ecu": m.ecu,
            "role": m.role,
            "pci": PCI_NAMES[info.pci_type],
            "isotp": info.to_dict(),
        }
        if info.pci_type in (PciType.SF, PciType.FF) and info.data:
            d["sid"] = info.data[0]
            d["first_bytes"] = info.data[:4].hex(" ").upper()
            if info.pci_type == PciType.SF:
                d["payload"] = info.data
        return d

    def feed(self, frame: CanFrame) -> None:
        m = self.match(frame)
        if not m:
            return
        key = (frame.channel, frame.arbitration_id, frame.is_extended_id)
        try:
            info = parse_frame(frame.data, m.profile.addressing)
        except IsoTpError:
            return
        if info.pci_type == PciType.SF:
            self._partials.pop(key, None)
            self._emit(m, frame, info.data, frame.timestamp, 1)
        elif info.pci_type == PciType.FF:
            self._partials[key] = _Partial(
                info.length or 0,
                bytearray(info.data[: info.length]),
                1,
                frame.timestamp,
                1,
                m,
                frame.direction,
            )
        elif info.pci_type == PciType.CF:
            part = self._partials.get(key)
            if not part:
                return
            if info.seq != part.seq:
                self._partials.pop(key, None)
                self.on_message(
                    {
                        "ts": frame.timestamp,
                        "channel": frame.channel,
                        "ecu": m.ecu,
                        "role": m.role,
                        "dir": frame.direction,
                        "error": f"Sequenzfehler (erwartet {part.seq}, erhalten {info.seq})",
                        "can_id": frame.arbitration_id,
                        "payload": part.data.hex(" ").upper(),
                    }
                )
                return
            part.seq = (part.seq + 1) & 0x0F
            part.frames += 1
            part.data += info.data[: part.expected - len(part.data)]
            if len(part.data) >= part.expected:
                self._partials.pop(key, None)
                self._emit(m, frame, bytes(part.data), part.t_first, part.frames)

    def _emit(self, m: EndpointMatch, frame: CanFrame, payload: bytes, t_first: float, frames: int) -> None:
        self.on_message(
            {
                "ts": t_first,
                "ts_end": frame.timestamp,
                "channel": frame.channel,
                "ecu": m.ecu,
                "role": m.role,
                "dir": frame.direction,
                "can_id": frame.arbitration_id,
                "frames": frames,
                "payload_bytes": payload,
            }
        )
