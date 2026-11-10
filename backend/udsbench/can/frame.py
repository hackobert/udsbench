"""Interne, adapterunabhängige CAN-Frame-Repräsentation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.hexutil import ascii_preview, to_hex

#: Gültige CAN-FD-Nutzdatenlängen (DLC 0..15)
FD_LENGTHS: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)


def next_fd_length(n: int) -> int:
    """Kleinste gültige CAN-FD-Datenlänge >= n."""
    for length in FD_LENGTHS:
        if length >= n:
            return length
    raise ValueError(f"CAN-FD-Frame zu lang: {n} Byte")


def length_to_dlc(n: int) -> int:
    return FD_LENGTHS.index(next_fd_length(n))


@dataclass(slots=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False
    is_fd: bool = False
    bitrate_switch: bool = False
    is_error_frame: bool = False
    is_remote_frame: bool = False
    timestamp: float = field(default_factory=time.time)
    direction: str = "rx"  # "rx" | "tx"
    channel: str = "default"

    @property
    def dlc(self) -> int:
        return length_to_dlc(len(self.data)) if self.is_fd else len(self.data)

    def id_str(self) -> str:
        return f"{self.arbitration_id:08X}" if self.is_extended_id else f"{self.arbitration_id:03X}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.timestamp,
            "channel": self.channel,
            "dir": self.direction,
            "id": self.arbitration_id,
            "id_hex": self.id_str(),
            "ext": self.is_extended_id,
            "fd": self.is_fd,
            "brs": self.bitrate_switch,
            "err": self.is_error_frame,
            "rtr": self.is_remote_frame,
            "dlc": self.dlc,
            "len": len(self.data),
            "data": to_hex(self.data),
            "ascii": ascii_preview(self.data),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CanFrame:
        from ..core.hexutil import parse_hex

        raw_id = d.get("id", d.get("id_hex", 0))
        return cls(
            arbitration_id=raw_id if isinstance(raw_id, int) else int(str(raw_id).removeprefix("0x"), 16),
            data=parse_hex(d.get("data", "")),
            is_extended_id=bool(d.get("ext", False)),
            is_fd=bool(d.get("fd", False)),
            bitrate_switch=bool(d.get("brs", False)),
            is_error_frame=bool(d.get("err", False)),
            is_remote_frame=bool(d.get("rtr", False)),
            timestamp=float(d.get("ts", time.time())),
            direction=str(d.get("dir", "rx")),
            channel=str(d.get("channel", "default")),
        )
