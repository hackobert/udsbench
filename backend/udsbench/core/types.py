"""Gemeinsame pydantic-Typen (Hex-tolerante Integer usw.)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

from .hexutil import parse_hex, parse_int, to_hex


def _int(v: object) -> int:
    return parse_int(v)


def _byte(v: object) -> int:
    i = parse_int(v)
    if not 0 <= i <= 0xFF:
        raise ValueError(f"Byte-Wert außerhalb 0x00..0xFF: {v!r}")
    return i


def _bytes(v: object) -> bytes:
    return parse_hex(v)  # type: ignore[arg-type]


HexInt = Annotated[int, BeforeValidator(_int)]
HexByte = Annotated[int, BeforeValidator(_byte)]
HexBytes = Annotated[bytes, BeforeValidator(_bytes), PlainSerializer(lambda b: to_hex(b), return_type=str)]
