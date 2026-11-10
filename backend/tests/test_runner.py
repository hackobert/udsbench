"""Test-Runner, Assertions, Datensätze, Negativtests, Reports (JSON/JUnit), Abbruch."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET

import pytest

from udsbench.messages.models import Expect
from udsbench.testrunner.assertions import check_expect, match_hex_pattern
from udsbench.testrunner.models import TestDef
from udsbench.uds.client import UdsResult

pytestmark = pytest.mark.integration


def test_hex_pattern():
    assert match_hex_pattern("62 F1 ?? *", bytes.fromhex("62F19011"))
    assert match_hex_pattern("62F190", bytes.fromhex("62F190"))
    assert not match_hex_pattern("62 F1", bytes.fromhex("62F190"))


def test_check_expect_variants():
    r = UdsResult(
        "e", bytes.fromhex("2701"), response=bytes.fromhex("7F2735"), t_tx_done=1.0, t_response=1.01
    )
    res = check_expect(Expect(nrc="invalidKey", max_time_ms=20, positive=False), r, {})
    assert all(a.ok for a in res), res
    res = check_expect(Expect(nrc=[0x22, 0x33]), r, {})
    assert not res[0].ok
    ok = UdsResult(
        "e", bytes.fromhex("22F190"), response=bytes.fromhex("62F19041"), t_tx_done=0, t_response=0.001
    )
    res = check_expect(
        Expect(response_prefix="62 F1 90", length=4, expr="response[3] == 0x41"),
        ok,
        {"response": ok.response},
    )
    assert all(a.ok for a in res)
    to = UdsResult("e", bytes.fromhex("22F190"), error="Timeout", error_kind="timeout")
    assert check_expect(Expect(no_response=True), to, {})[0].ok
    assert not check_expect(Expect(no_response=False), to, {})[0].ok


async def test_demo_suite_passes(platform):
    run = platform.runner.start_suite("full")
    await platform.runner.wait(run.id, 60)
    bad = [(t.label, t.message) for t in run.tests if t.status != "passed"]
    assert run.status == "passed", bad
    assert len(run.tests) == 12  # inkl. 3 Datensätze
    rep = run.to_dict()
    assert rep["environment"]["packages"][0]["id"] == "demo" and rep["environment"]["packages"][0]["hash"]
    assert (platform.runner.reports_dir / f"{run.id}.json").exists()


async def test_junit_report_is_valid_xml(platform):
    t = TestDef.model_validate(
        {
            "id": "neg",
            "name": "Fehlschlag",
            "ecu": "ecu_a",
            "steps": [{"send": {"payload": "22 F1 00"}, "expect": {"nrc": 0x31}}],
        }
    )
    run = platform.runner.start_adhoc("test", "neg", "neg", [t])
    await platform.runner.wait(run.id, 10)
    assert run.status == "failed"
    xml = platform.runner.report(run.id, "junit")
    root = ET.fromstring(xml)
    assert root.attrib["failures"] == "1"
    tc = root.find("./testsuite/testcase")
    assert tc is not None and tc.find("failure") is not None
    assert "nrc" in (tc.find("failure").text or "")  # type: ignore[union-attr]


async def test_expected_failure_and_datasets(platform):
    t = TestDef.model_validate(
        {
            "id": "dd",
            "ecu": "ecu_a",
            "datasets": [{"did": "F100"}, {"did": "F101"}, {"did": "DEAD"}],
            "steps": [{"send": {"payload": "22 ${did}"}, "expect": {"positive": True}}],
        }
    )
    neg = TestDef.model_validate(
        {
            "id": "neg",
            "ecu": "ecu_a",
            "expected_result": "fail",
            "steps": [{"send": {"payload": "22 DE AD"}, "expect": {"positive": True}}],
        }
    )
    run = platform.runner.start_adhoc("test", "dd", "dd", [t, neg])
    await platform.runner.wait(run.id, 10)
    assert [x.status for x in run.tests] == ["passed", "passed", "failed", "passed"]


async def test_setup_failure_marks_error_and_teardown_runs(platform):
    t = TestDef.model_validate(
        {
            "id": "s",
            "ecu": "ecu_a",
            "setup": [{"session": 0x04}],
            "steps": [{"send": {"payload": "3E 00"}}],
            "teardown": [{"log": "teardown ran"}],
        }
    )
    run = platform.runner.start_adhoc("test", "s", "s", [t])
    await platform.runner.wait(run.id, 10)
    assert run.tests[0].status == "error" and "teardown ran" in run.tests[0].log


async def test_cancel_run(platform):
    t = TestDef.model_validate({"id": "slow", "ecu": "ecu_a", "steps": [{"wait": 5000}]})
    run = platform.runner.start_adhoc("test", "slow", "slow", [t])
    await asyncio.sleep(0.1)
    platform.runner.cancel(run.id)
    await platform.runner.wait(run.id, 5)
    assert run.status == "cancelled"


async def test_sequence_variables_and_control_flow(platform):
    run = platform.runner.start_sequence("read_all_ids")
    await platform.runner.wait(run.id, 10)
    assert run.status == "passed"
    steps = run.tests[0].steps
    assert any(s.action == "if" and s.details.get("condition") is True for s in steps)
    t = TestDef.model_validate(
        {
            "id": "loop",
            "ecu": "ecu_a",
            "vars": {"n": 0},
            "steps": [
                {"repeat": {"count": 10, "until": "n >= 3", "steps": [{"set": {"n": "=n+1"}}]}},
                {"assert": "n == 3"},
            ],
        }
    )
    run = platform.runner.start_adhoc("test", "loop", "loop", [t])
    await platform.runner.wait(run.id, 10)
    assert run.status == "passed"


async def test_custom_assertion_plugin(platform):
    from udsbench.plugins.registry import registry

    registry.add_assertion("len_even", lambda ctx, res, params: (len(res.response) % 2 == 0, "Länge gerade?"))
    t = TestDef.model_validate(
        {
            "id": "c",
            "ecu": "ecu_a",
            "steps": [{"send": {"payload": "3E 00"}, "expect": {"custom": [{"name": "len_even"}]}}],
        }
    )
    run = platform.runner.start_adhoc("test", "c", "c", [t])
    await platform.runner.wait(run.id, 10)
    assert run.status == "passed"
