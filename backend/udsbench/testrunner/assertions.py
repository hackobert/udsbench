"""Assertion-Auswertung für Schritte (positive Response, NRC, Bytes, Felder, Zeit, Timeout …)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.hexutil import to_hex
from ..messages.expr import ExprError, evaluate
from ..messages.models import Expect
from ..uds.client import UdsResult
from ..uds.nrc import nrc_name, parse_nrc


@dataclass
class AssertionResult:
    name: str
    ok: bool
    message: str
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


def match_hex_pattern(pattern: str, data: bytes) -> bool:
    toks = pattern.replace(",", " ").split()
    if len(toks) == 1 and len(toks[0]) > 2 and toks[0] != "*":
        t = toks[0]
        toks = [t[i : i + 2] for i in range(0, len(t), 2)]
    rest = bool(toks) and toks[-1] == "*"
    if rest:
        toks = toks[:-1]
    if len(toks) > len(data) or (not rest and len(toks) != len(data)):
        return False
    return all(t in ("??", "XX", "xx") or int(t, 16) == b for t, b in zip(toks, data, strict=False))


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = cur[int(part)]
        else:
            return None
    return cur


def check_expect(
    exp: Expect, res: UdsResult | None, env: dict[str, Any], ctx: Any = None
) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    resp = res.response if res else None
    timeout = res is None or (res.response is None and (res.error_kind == "timeout" or res.suppress_positive))

    if exp.no_response is not None:
        ok = (resp is None) == exp.no_response
        out.append(
            AssertionResult(
                "no_response",
                ok,
                "keine Antwort" if resp is None else f"Antwort {to_hex(resp)}",
                exp.no_response,
                resp is None,
            )
        )
    elif res is not None and res.error and res.error_kind not in ("timeout",) and not res.suppress_positive:
        out.append(AssertionResult("transport", False, res.error))
    if exp.positive is not None:
        if res is not None and res.suppress_positive and resp is None and exp.positive:
            out.append(AssertionResult("positive", True, "positive Antwort unterdrückt (SPRMIB) – keine NRC"))
        else:
            actual = bool(res and res.positive)
            msg = (
                "positive Response"
                if actual
                else (
                    f"NRC 0x{res.nrc:02X} {nrc_name(res.nrc)}"
                    if res and res.nrc is not None
                    else (res.error if res and res.error else "keine positive Response")
                )
            )
            out.append(AssertionResult("positive", actual == exp.positive, msg, exp.positive, actual))
    if exp.nrc is not None:
        wanted = [parse_nrc(n) for n in (exp.nrc if isinstance(exp.nrc, list) else [exp.nrc])]
        actual_nrc = res.nrc if res else None
        ok = actual_nrc in wanted
        out.append(
            AssertionResult(
                "nrc",
                ok,
                f"NRC 0x{actual_nrc:02X} {nrc_name(actual_nrc)}"
                if actual_nrc is not None
                else ("keine Antwort" if timeout else f"keine NRC ({to_hex(resp)})"),
                [f"0x{w:02X} {nrc_name(w)}" for w in wanted],
                f"0x{actual_nrc:02X}" if actual_nrc is not None else None,
            )
        )
    if exp.response is not None:
        ok = resp is not None and match_hex_pattern(exp.response, resp)
        out.append(
            AssertionResult(
                "response",
                ok,
                f"Antwort {to_hex(resp)}" if resp else "keine Antwort",
                exp.response,
                to_hex(resp),
            )
        )
    if exp.response_prefix is not None:
        pref = exp.response_prefix.strip()
        ok = resp is not None and match_hex_pattern(pref + " *", resp)
        out.append(
            AssertionResult(
                "response_prefix",
                ok,
                f"Antwort {to_hex(resp)}" if resp else "keine Antwort",
                pref,
                to_hex(resp),
            )
        )
    if exp.length is not None:
        n = len(resp) if resp else 0
        out.append(AssertionResult("length", n == exp.length, f"Länge {n}", exp.length, n))
    if exp.min_length is not None:
        n = len(resp) if resp else 0
        out.append(AssertionResult("min_length", n >= exp.min_length, f"Länge {n}", exp.min_length, n))
    if exp.max_time_ms is not None:
        t = res.elapsed_ms if res else None
        out.append(
            AssertionResult(
                "max_time_ms",
                t is not None and t <= exp.max_time_ms,
                f"Antwortzeit {t} ms",
                exp.max_time_ms,
                t,
            )
        )
    if exp.min_time_ms is not None:
        t = res.elapsed_ms if res else None
        out.append(
            AssertionResult(
                "min_time_ms",
                t is not None and t >= exp.min_time_ms,
                f"Antwortzeit {t} ms",
                exp.min_time_ms,
                t,
            )
        )
    if exp.pending_max is not None:
        p = res.pending_count if res else 0
        out.append(
            AssertionResult("pending_max", p <= exp.pending_max, f"{p}x ResponsePending", exp.pending_max, p)
        )
    if exp.responses_min is not None:
        n = len(res.responses) if res else 0
        out.append(
            AssertionResult("responses_min", n >= exp.responses_min, f"{n} Antwort(en)", exp.responses_min, n)
        )
    if exp.fields:
        decoded = res.decoded if res else {}
        for path, want in exp.fields.items():
            got = _get_path(decoded, path)
            out.append(AssertionResult(f"field:{path}", got == want, f"{path} = {got!r}", want, got))
    if exp.expr:
        for e in [exp.expr] if isinstance(exp.expr, str) else exp.expr:
            try:
                v = evaluate(e, env)
                out.append(AssertionResult(f"expr:{e}", bool(v), f"{e} → {v!r}"))
            except ExprError as exc:
                out.append(AssertionResult(f"expr:{e}", False, str(exc)))
    if exp.custom:
        from ..plugins.registry import registry

        for c in exp.custom:
            fn = registry.assertions.get(c.name)
            if fn is None:
                out.append(AssertionResult(f"custom:{c.name}", False, "Assertion-Plugin nicht registriert"))
                continue
            try:
                ok, msg = fn(ctx, res, c.params)
                out.append(AssertionResult(f"custom:{c.name}", bool(ok), str(msg)))
            except Exception as exc:
                out.append(AssertionResult(f"custom:{c.name}", False, f"Fehler: {exc}"))
    return out
