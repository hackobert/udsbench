"""Konformität Timing/Session (ISO 14229-2): P2/P2*, 0x78, SPRMIB, S3/TesterPresent, funktional."""

from __future__ import annotations

import asyncio
import time

import pytest

from udsbench.config.schema import ConnectionSpec

from .conftest import unique_bus

pytestmark = [pytest.mark.conformance, pytest.mark.integration]

TIMING_PACKAGE = {
    "package": {"id": "timing_test", "version": "1.0.0"},
    "isotp_profiles": {"p": {"tx_id": 0x600, "rx_id": 0x608, "functional_id": 0x6FF}},
    "ecus": [
        {
            "id": "ecu_t",
            "isotp": "p",
            "timing": {"p2_ms": 50, "p2_star_ms": 300, "margin_ms": 50, "max_response_pending": 5},
            "tester_present": {
                "enabled": True,
                "interval_ms": 200,
                "suppress_response": True,
                "s3_server_ms": 600,
            },
        }
    ],
    "simulation": {
        "ecus": [
            {
                "ecu": "ecu_t",
                "p2_server_max_ms": 25,
                "p2_star_server_max_ms": 300,
                "s3_server_ms": 600,
                "dids": [{"id": 0x1234, "value": "01"}],
                "overrides": [
                    {"match": "31 01 AB CD", "respond": "71 01 AB CD 00", "pending": 3, "delay_ms": 150},
                    {"match": "22 AA AA", "respond": None},
                    {"match": "22 BB BB", "respond": "62 BB BB 00", "pending": 10, "delay_ms": 20},
                    {"match": "22 CC CC", "respond": "62 CC CC 00", "delay_ms": 400},
                    {"match": "11 81", "respond": "7F 11 22"},
                ],
            }
        ]
    },
}


@pytest.fixture
async def tplat(platform):
    platform.packages.add(TIMING_PACKAGE, activate=True)
    await platform.settle()
    return platform


async def test_response_pending_extends_to_p2_star(tplat):
    rt = tplat.diag.get("ecu_t")
    res = await rt.request(bytes.fromhex("3101ABCD"))
    assert res.positive and res.pending_count == 3
    assert res.elapsed_ms > 3 * 140  # länger als P2 – nur dank P2*-Verlängerung erfolgreich


async def test_response_pending_limit(tplat):
    rt = tplat.diag.get("ecu_t")
    res = await rt.request(bytes.fromhex("22BBBB"))
    assert res.error_kind == "pending_limit" and res.pending_count == 6


async def test_p2_timeout(tplat):
    rt = tplat.diag.get("ecu_t")
    t0 = time.perf_counter()
    res = await rt.request(bytes.fromhex("22AAAA"))
    assert res.error_kind == "timeout" and res.response is None
    assert 0.09 <= time.perf_counter() - t0 < 0.4  # P2 (50) + margin (50)


async def test_late_response_is_timeout(tplat):
    rt = tplat.diag.get("ecu_t")
    res = await rt.request(bytes.fromhex("22CCCC"))
    assert res.error_kind == "timeout"
    await asyncio.sleep(0.4)
    res2 = await rt.request(bytes.fromhex("221234"))  # verspätete Antwort darf nicht zugeordnet werden
    assert res2.positive and res2.response == bytes.fromhex("62123401")


async def test_adopts_p2_from_session_response(tplat):
    rt = tplat.diag.get("ecu_t")
    res = await rt.request(bytes.fromhex("1003"))
    assert res.positive and rt.session == 3
    assert rt.timing.p2_ms == 25 and rt.timing.p2_star_ms == 300


async def test_suppress_positive_response(tplat):
    rt = tplat.diag.get("ecu_t")
    res = await rt.request(bytes.fromhex("1083"))
    assert res.response is None and res.error is None and res.suppress_positive
    assert rt.session == 3  # Zustandswechsel trotz unterdrückter Antwort übernommen
    nrc = await rt.request(bytes.fromhex("1181"))  # NRC wird trotz SPRMIB gemeldet
    assert nrc.nrc == 0x22


async def test_tester_present_keeps_session_alive(tplat):
    rt = tplat.diag.get("ecu_t")
    await rt.request(bytes.fromhex("1003"))
    await asyncio.sleep(1.0)  # > S3server (600 ms)
    assert rt.tp_sent >= 3
    sim = tplat.sim.get("ecu_t")
    res = await rt.request(bytes.fromhex("221234"))
    assert res.positive and sim.session == 3


async def test_s3_fallback_without_tester_present(tplat):
    rt = tplat.diag.get("ecu_t")
    rt.tp_enabled = False
    await rt.request(bytes.fromhex("1003"))
    await asyncio.sleep(0.9)
    assert rt.session == 1  # Tester erkennt Rückfall lokal
    await rt.request(bytes.fromhex("3E00"))
    assert tplat.sim.get("ecu_t").session == 1  # ECU ist ebenfalls zurückgefallen


async def test_functional_addressing_collects_multiple_responses(platform):
    rt = platform.diag.get("ecu_a")
    res = await rt.request(bytes.fromhex("22F101"), functional=True)
    ecus = sorted(r.ecu for r in res.responses)
    assert ecus == ["ecu_a", "ecu_c"]
    assert all(r.payload.startswith(bytes.fromhex("62F101")) for r in res.responses)


async def test_functional_suppresses_nrc_0x11(platform):
    rt = platform.diag.get("ecu_a")
    res = await rt.request(bytes.fromhex("3F00"), functional=True, validate="off")
    assert res.responses == []  # NRC 0x11 wird funktional nicht gesendet
    phys = await rt.request(bytes.fromhex("3F00"), validate="off")
    assert phys.nrc == 0x11


async def test_ecu_reset_returns_to_default(platform):
    rt = platform.diag.get("ecu_a")
    await rt.request(bytes.fromhex("1003"))
    assert rt.session == 3
    await rt.request(bytes.fromhex("1101"))
    assert rt.session == 1


async def test_not_connected_error(tmp_path):
    from udsbench.core.errors import NotConnectedError
    from udsbench.core.platform import Platform

    from .conftest import make_config

    p = Platform(make_config(tmp_path), tmp_path)
    await p.start()
    with pytest.raises(NotConnectedError):
        p.diag.get("ecu_a")
    await p.connect(ConnectionSpec(name="default", backend="virtual", options={"bus": unique_bus()}))
    res = await p.diag.get("ecu_a").request(bytes.fromhex("3E00"))
    assert res.error_kind == "timeout"  # kein Testdouble → Timeout statt Hängen
    await p.stop()
