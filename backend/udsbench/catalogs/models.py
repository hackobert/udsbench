"""Kataloge: DIDs, DTCs, Routinen – inkl. typgerechter Kodierung/Dekodierung."""

from __future__ import annotations

import struct
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.hexutil import parse_hex, to_hex
from ..core.types import HexInt

DataType = Literal[
    "uint", "int", "float32", "float64", "ascii", "utf8", "hex", "bcd", "enum", "bitfield", "bool"
]


class BitField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    bit: int = Field(..., ge=0, description="Startbit (0 = LSB des gesamten Werts)")
    length: int = Field(1, ge=1)
    enum: dict[int, str] | None = None


class ValueSpec(BaseModel):
    """Beschreibt die Kodierung eines Werts (DID-Daten, Routine-Parameter, Ergebnisfelder)."""

    model_config = ConfigDict(extra="forbid")
    type: DataType = "hex"
    length: int | None = Field(None, ge=0, description="Länge in Byte (None = variabel/Rest)")
    byteorder: Literal["big", "little"] = "big"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    enum: dict[int, str] | None = None
    bits: list[BitField] | None = None
    min: float | None = None
    max: float | None = None
    decoder: str | None = Field(None, description="Name eines registrierten Decoder-Plugins")

    def decode(self, data: bytes) -> Any:
        if self.decoder:
            from ..plugins.registry import registry

            fn = registry.decoders.get(self.decoder)
            if fn is None:
                raise ValueError(f"Decoder-Plugin {self.decoder!r} nicht registriert")
            return fn(data, self)
        t = self.type
        bo = self.byteorder
        if t in ("uint", "int", "enum", "bool", "bitfield"):
            raw = int.from_bytes(data, bo, signed=(t == "int")) if data else 0
            if t == "bool":
                return bool(raw)
            if t == "enum":
                return (self.enum or {}).get(raw, f"0x{raw:X}")
            if t == "bitfield":
                out: dict[str, Any] = {}
                for bf in self.bits or []:
                    v = (raw >> bf.bit) & ((1 << bf.length) - 1)
                    out[bf.name] = (bf.enum or {}).get(v, v) if bf.enum else v
                return out
            if self.scale != 1.0 or self.offset != 0.0:
                return round(raw * self.scale + self.offset, 9)
            return raw
        if t in ("float32", "float64"):
            fmt = (">" if bo == "big" else "<") + ("f" if t == "float32" else "d")
            return round(struct.unpack(fmt, data)[0] * self.scale + self.offset, 9)
        if t == "ascii":
            return data.decode("ascii", errors="replace").rstrip("\x00")
        if t == "utf8":
            return data.decode("utf-8", errors="replace").rstrip("\x00")
        if t == "bcd":
            return "".join(f"{b >> 4:X}{b & 0xF:X}" for b in data)
        return to_hex(data)

    def encode(self, value: Any) -> bytes:
        t = self.type
        bo = self.byteorder
        n = self.length
        if t == "hex" or isinstance(value, (bytes, bytearray)):
            data = parse_hex(value) if not isinstance(value, (bytes, bytearray)) else bytes(value)
        elif t in ("uint", "int", "bool"):
            if t == "bool":
                raw = 1 if value in (True, 1, "1", "true", "True") else 0
            else:
                num = float(value)
                if (self.min is not None and num < self.min) or (self.max is not None and num > self.max):
                    raise ValueError(f"Wert {value} außerhalb [{self.min}, {self.max}]")
                raw = round((num - self.offset) / self.scale)
            data = int(raw).to_bytes(n or max(1, (int(raw).bit_length() + 8) // 8), bo, signed=(t == "int"))  # type: ignore[arg-type]
        elif t == "enum":
            inv = {v: k for k, v in (self.enum or {}).items()}
            raw = inv[value] if value in inv else int(str(value), 0)
            data = raw.to_bytes(n or 1, bo)  # type: ignore[arg-type]
        elif t == "bitfield":
            raw = 0
            for bf in self.bits or []:
                v = value.get(bf.name, 0) if isinstance(value, dict) else 0
                if bf.enum and isinstance(v, str):
                    v = {name: k for k, name in bf.enum.items()}[v]
                raw |= (int(v) & ((1 << bf.length) - 1)) << bf.bit
            data = raw.to_bytes(n or 1, bo)  # type: ignore[arg-type]
        elif t in ("float32", "float64"):
            fmt = (">" if bo == "big" else "<") + ("f" if t == "float32" else "d")
            data = struct.pack(fmt, (float(value) - self.offset) / self.scale)
        elif t in ("ascii", "utf8"):
            data = str(value).encode("ascii" if t == "ascii" else "utf-8")
            if n is not None:
                if len(data) > n:
                    raise ValueError(f"Text länger als {n} Byte")
                data = data.ljust(n, b"\x00" if t == "utf8" else b" ")
        elif t == "bcd":
            s = str(value)
            if len(s) % 2:
                s = "0" + s
            data = bytes.fromhex(s)
        else:  # pragma: no cover
            raise ValueError(f"Unbekannter Typ {t}")
        if n is not None and len(data) != n:
            raise ValueError(f"Kodierter Wert hat {len(data)} Byte, erwartet {n}")
        return data


class DidDef(ValueSpec):
    id: HexInt
    name: str
    description: str = ""
    access: Literal["read", "write", "readwrite"] = "read"
    io_control: bool = Field(False, description="Über 0x2F steuerbar")
    io_control_spec: ValueSpec | None = None

    @model_validator(mode="after")
    def _chk(self) -> DidDef:
        if not 0 <= self.id <= 0xFFFF:
            raise ValueError("DID muss 16 Bit sein")
        return self

    def to_public(self) -> dict[str, Any]:
        d = self.model_dump()
        d["id_hex"] = f"0x{self.id:04X}"
        return d


class DtcDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: HexInt = Field(..., description="DTC (3 Byte)")
    name: str = ""
    description: str = ""
    severity: int | None = None

    def to_public(self) -> dict[str, Any]:
        d = self.model_dump()
        d["code_hex"] = f"{self.code:06X}"
        d["display"] = dtc_display(self.code)
        return d


class RoutineField(ValueSpec):
    name: str


class RoutineDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: HexInt
    name: str
    description: str = ""
    start_params: list[RoutineField] = Field(default_factory=list)
    stop_params: list[RoutineField] = Field(default_factory=list)
    result_fields: list[RoutineField] = Field(default_factory=list)
    supports: list[Literal["start", "stop", "results"]] = Field(
        default_factory=lambda: ["start", "stop", "results"]
    )

    def to_public(self) -> dict[str, Any]:
        d = self.model_dump()
        d["id_hex"] = f"0x{self.id:04X}"
        return d


class Catalogs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dids: list[DidDef] = Field(default_factory=list)
    dtcs: list[DtcDef] = Field(default_factory=list)
    routines: list[RoutineDef] = Field(default_factory=list)


def dtc_display(code: int) -> str:
    """3-Byte-DTC in SAE-J2012-Darstellung (Pxxxx-yy) – nur als Darstellungshilfe."""
    hi = (code >> 16) & 0xFF
    letter = "PCBU"[hi >> 6]
    return f"{letter}{(hi >> 4) & 0x3:X}{hi & 0xF:X}{(code >> 8) & 0xFF:02X}-{code & 0xFF:02X}"


def decode_fields(fields: list[RoutineField], data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pos = 0
    for f in fields:
        chunk = data[pos:] if f.length is None else data[pos : pos + f.length]
        pos += len(chunk)
        try:
            out[f.name] = f.decode(chunk)
        except Exception as exc:  # pragma: no cover
            out[f.name] = f"<Fehler: {exc}>"
    if pos < len(data):
        out["_rest"] = to_hex(data[pos:])
    return out


def encode_fields(fields: list[RoutineField], values: dict[str, Any]) -> bytes:
    return b"".join(f.encode(values[f.name]) for f in fields if f.name in values)
