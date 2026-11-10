"""Sichere Ausdrucksauswertung und Platzhalter-Auflösung für Vorlagen, Sequenzen und Assertions.

Erlaubt: Literale, Variablen, Attribut-/Schlüsselzugriff, Index/Slice, Arithmetik, Bit-Operatoren,
Vergleiche, and/or/not, bedingte Ausdrücke und eine Whitelist an Funktionen. Kein Import, keine
Dunder-Attribute, keine beliebigen Aufrufe.
"""

from __future__ import annotations

import ast
import operator
import re
import zlib
from collections.abc import Callable
from typing import Any

from ..core.hexutil import parse_hex, to_hex


class ExprError(ValueError):
    pass


class Ns(dict):  # type: ignore[type-arg]
    """dict mit Attributzugriff (ecu.tx_id)."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


def _bytes(v: Any) -> bytes:
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if isinstance(v, int):
        return v.to_bytes(max(1, (v.bit_length() + 7) // 8), "big")
    if isinstance(v, list):
        return bytes(v)
    return parse_hex(str(v))


def _uint(n: int) -> Callable[[Any], bytes]:
    return lambda v: (int(v) & ((1 << (8 * n)) - 1)).to_bytes(n, "big")


def _crc16_ccitt(data: Any, init: int = 0xFFFF) -> int:
    crc = init
    for b in _bytes(data):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "len": len,
    "int": lambda v, base=0: (
        int(v, base)
        if isinstance(v, str)
        else (int.from_bytes(v, "big") if isinstance(v, (bytes, bytearray)) else int(v))
    ),
    "hex": lambda v: to_hex(v) if isinstance(v, (bytes, bytearray)) else f"{int(v):X}",
    "str": str,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "bytes": _bytes,
    "u8": _uint(1),
    "u16": _uint(2),
    "u24": _uint(3),
    "u32": _uint(4),
    "u16le": lambda v: (int(v) & 0xFFFF).to_bytes(2, "little"),
    "u32le": lambda v: (int(v) & 0xFFFFFFFF).to_bytes(4, "little"),
    "be": lambda b: int.from_bytes(_bytes(b), "big"),
    "le": lambda b: int.from_bytes(_bytes(b), "little"),
    "ascii": lambda v: (
        _bytes(v).decode("ascii", "replace") if isinstance(v, (bytes, bytearray)) else str(v).encode("ascii")
    ),
    "concat": lambda *parts: b"".join(_bytes(p) for p in parts),
    "bxor": lambda b, m: bytes(
        x ^ (m if isinstance(m, int) else _bytes(m)[i % len(_bytes(m))]) for i, x in enumerate(_bytes(b))
    ),
    "invert": lambda b: bytes(x ^ 0xFF for x in _bytes(b)),
    "repeat": lambda b, n: _bytes(b) * int(n),
    "zeros": lambda n: bytes(int(n)),
    "crc32": lambda b: zlib.crc32(_bytes(b)) & 0xFFFFFFFF,
    "crc16": _crc16_ccitt,
    "sum8": lambda b: sum(_bytes(b)) & 0xFF,
    "contains": lambda a, b: _bytes(b) in _bytes(a),
    "startswith": lambda a, b: _bytes(a).startswith(_bytes(b)),
}

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.Pow: operator.pow,
}
_CMP: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def _eval(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        raise ExprError(f"Unbekannte Variable {node.id!r}")
    if isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise ExprError("Zugriff auf private Attribute nicht erlaubt")
        base = _eval(node.value, env)
        if isinstance(base, dict):
            if node.attr in base:
                return base[node.attr]
            raise ExprError(f"Feld {node.attr!r} nicht vorhanden")
        if hasattr(base, "expr_fields"):
            fields = base.expr_fields()
            if node.attr in fields:
                return fields[node.attr]
        raise ExprError(f"Attribut {node.attr!r} nicht verfügbar")
    if isinstance(node, ast.Subscript):
        base = _eval(node.value, env)
        sl = node.slice
        if isinstance(sl, ast.Slice):
            lo = _eval(sl.lower, env) if sl.lower else None
            hi = _eval(sl.upper, env) if sl.upper else None
            st = _eval(sl.step, env) if sl.step else None
            return base[lo:hi:st]
        try:
            return base[_eval(sl, env)]
        except (IndexError, KeyError, TypeError) as exc:
            raise ExprError(f"Index-Fehler: {exc}") from exc
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ExprError("Operator nicht erlaubt")
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and isinstance(right, int) and right > 64:
            raise ExprError("Exponent zu groß")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not v
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.Invert):
            return ~v
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = _eval(v, env)
                if not result:
                    return result
            return result
        result = False
        for v in node.values:
            result = _eval(v, env)
            if result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for cop, comp in zip(node.ops, node.comparators, strict=False):
            right = _eval(comp, env)
            if not _CMP[type(cop)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise ExprError(f"Funktion nicht erlaubt: {ast.unparse(node.func)}")
        args = [_eval(a, env) for a in node.args]
        kwargs = {k.arg: _eval(k.value, env) for k in node.keywords if k.arg}
        return FUNCTIONS[node.func.id](*args, **kwargs)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, env) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {
            _eval(k, env): _eval(v, env)
            for k, v in zip(node.keys, node.values, strict=False)
            if k is not None
        }
    raise ExprError(f"Ausdruck nicht erlaubt: {type(node).__name__}")


def evaluate(expr: str, env: dict[str, Any]) -> Any:
    if len(expr) > 2000:
        raise ExprError("Ausdruck zu lang")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"Syntaxfehler in {expr!r}: {exc.msg}") from exc
    try:
        return _eval(tree, env)
    except ExprError:
        raise
    except Exception as exc:
        raise ExprError(f"Fehler in {expr!r}: {exc}") from exc


_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def render_value(v: Any) -> str:
    """Wert in Hex-Text für Nutzlast-Vorlagen."""
    if isinstance(v, (bytes, bytearray)):
        return to_hex(bytes(v))
    if isinstance(v, bool):
        return "01" if v else "00"
    if isinstance(v, int):
        return to_hex(v.to_bytes(max(1, (v.bit_length() + 7) // 8), "big"))
    if isinstance(v, list):
        return to_hex(bytes(v))
    return str(v)


def render_template(template: str, env: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: render_value(evaluate(m.group(1), env)), template)


def render_payload(template: str, env: dict[str, Any]) -> bytes:
    return parse_hex(render_template(template, env))


def resolve_value(v: Any, env: dict[str, Any]) -> Any:
    """Werte in set:/vars: – Strings mit ${...} oder '=' Präfix werden ausgewertet."""
    if isinstance(v, str):
        if v.startswith("="):
            return evaluate(v[1:], env)
        if "${" in v:
            m = _PLACEHOLDER.fullmatch(v.strip())
            if m:
                return evaluate(m.group(1), env)
            return render_template(v, env)
    return v
