"""Sichere Ausdrücke und Platzhalter-Auflösung."""

from __future__ import annotations

import pytest

from udsbench.messages.expr import ExprError, Ns, evaluate, render_payload, render_template, resolve_value


def test_templates():
    env = {"did": 0xF190, "seed": b"\x01\x02", "ecu": Ns(tx_id=0x7E0), "level": 1}
    assert render_payload("22 ${u16(did)}", env) == bytes.fromhex("22F190")
    assert render_payload("27 ${level+1} ${invert(seed)}", env) == bytes.fromhex("2702FEFD")
    assert render_template("${ecu.tx_id}", env) == "07 E0"
    assert render_payload("${concat(seed, 'FF')}", env) == bytes.fromhex("0102FF")


def test_evaluate_functions():
    env = {"response": bytes.fromhex("62F1904142")}
    assert evaluate("response[3:]", env) == b"AB"
    assert evaluate("be(response[1:3]) == 0xF190", env) is True
    assert evaluate("ascii(response[3:])", env) == "AB"
    assert evaluate("crc32(b'')", {}) == 0
    assert evaluate("crc16('313233343536373839')", {}) == 0x29B1
    assert evaluate("len(response) > 4 and response[0] == 0x62", env)


@pytest.mark.parametrize(
    "bad", ["__import__('os')", "().__class__", "open('x')", "x.__dict__", "2 ** 1000", "lambda: 1"]
)
def test_unsafe_rejected(bad: str):
    with pytest.raises(ExprError):
        evaluate(bad, {"x": {}})


def test_resolve_value():
    env = {"a": 5}
    assert resolve_value("=a*2", env) == 10
    assert resolve_value("${a}", env) == 5
    assert resolve_value("plain", env) == "plain"
    assert resolve_value(3, env) == 3
