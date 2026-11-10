"""Hilfsfunktionen für Hex-Darstellung und -Parsing."""

from __future__ import annotations

import re
from typing import Any

_HEX_CLEAN = re.compile(r"0x|0X|[\s,;:_\-]")


class HexParseError(ValueError):
    pass


def parse_hex(text: str | bytes | bytearray | list[int] | None) -> bytes:
    """Parst eine Hex-Darstellung tolerant ("22 F1 90", "0x22,0xF1", "22f190", [0x22, 0xF1])."""
    if text is None:
        return b""
    if isinstance(text, (bytes, bytearray)):
        return bytes(text)
    if isinstance(text, list):
        try:
            return bytes(int(v) & 0xFF if isinstance(v, int) else int(str(v), 16) for v in text)
        except ValueError as exc:
            raise HexParseError(str(exc)) from exc
    cleaned = _HEX_CLEAN.sub("", str(text))
    if len(cleaned) % 2:
        raise HexParseError(f"Ungerade Anzahl Hex-Ziffern: {text!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise HexParseError(f"Ungültige Hex-Zeichen in {text!r}") from exc


def to_hex(data: bytes | bytearray | None, sep: str = " ") -> str:
    if not data:
        return ""
    return data.hex(sep).upper() if sep else data.hex().upper()


def parse_int(value: Any) -> int:
    """Akzeptiert int, "0x7E0", "7E0h", "123"."""
    if isinstance(value, bool):
        raise ValueError("bool ist kein Integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    s = str(value).strip()
    if not s:
        raise ValueError("leerer Wert")
    if s.lower().startswith("0x"):
        return int(s, 16)
    if s.lower().endswith("h"):
        return int(s[:-1], 16)
    if s.lower().startswith("0b"):
        return int(s, 2)
    return int(s, 10)


def int_to_bytes(value: int, length: int | None = None, byteorder: str = "big") -> bytes:
    if length is None:
        length = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(length, byteorder)  # type: ignore[arg-type]


def ascii_preview(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)
