"""Trace-Klassifizierung, Nachrichten-Rekonstruktion, Trace-Formate, Aufzeichnung & Replay."""

from __future__ import annotations

import asyncio

import pytest

from udsbench.can.frame import CanFrame
from udsbench.logs.traceformats import FORMATS, export_frames, import_frames


def _frames() -> list[CanFrame]:
    return [
        CanFrame(0x700, bytes.fromhex("0322F100CCCCCCCC"), timestamp=1000.0, direction="tx"),
        CanFrame(
            0x708, bytes.fromhex("10146 2F10044454D".replace(" ", "")), timestamp=1000.001, direction="rx"
        ),
        CanFrame(
            0x18DA10F1, bytes.fromhex("023E80"), is_extended_id=True, timestamp=1000.002, direction="tx"
        ),
        CanFrame(
            0x123, bytes(range(20)), is_fd=True, bitrate_switch=True, timestamp=1000.003, direction="rx"
        ),
    ]


@pytest.mark.parametrize("fmt", FORMATS)
def test_trace_formats_roundtrip(fmt: str):
    frames = _frames()
    text = export_frames(frames, fmt)
    back, meta = import_frames(text, fmt)
    assert len(back) == len(frames)
    for a, b in zip(frames, back, strict=True):
        assert (a.arbitration_id, a.data, a.is_extended_id, a.is_fd, a.direction) == (
            b.arbitration_id,
            b.data,
            b.is_extended_id,
            b.is_fd,
            b.direction,
        )
    # Zeitbasis bleibt erhalten (relativ)
    rel = [round(f.timestamp - back[0].timestamp, 6) for f in back]
    assert rel == [0.0, 0.001, 0.002, 0.003]


async def test_trace_classification_and_messages(platform):
    rt = platform.diag.get("ecu_a")
    await rt.request(bytes.fromhex("22F100"))
    await rt.request(bytes.fromhex("3E00"))
    await rt.request(bytes.fromhex("2701"))
    await rt.request(bytes.fromhex("1004"))
    frames = platform.trace.query("frames", 0, 100)
    pcis = {f.get("pci") for f in frames}
    assert {"SF", "FF", "CF", "FC"} <= pcis
    kinds = {f.get("uds") for f in frames if f.get("uds")}
    assert {"request", "positive", "negative", "segmented"} <= kinds
    msgs = platform.trace.query("messages", 0, 100)
    long_msg = next(m for m in msgs if m["payload"].startswith("62 F1 00"))
    assert (
        long_msg["frames"] > 1
        and long_msg["len"] == 20
        and "demo_identifier=DEMO-ECU-A-000001" in long_msg["text"]
    )
    assert {m["nrc"] for m in msgs if m["uds"] == "negative"} == {0x7F, 0x12}


async def test_record_export_import_replay(platform):
    rec = platform.recorder.start("t")
    rt = platform.diag.get("ecu_a")
    await rt.request(bytes.fromhex("3E00"))
    await rt.request(bytes.fromhex("22F101"))
    info = platform.recorder.stop()
    assert info["frames"] >= 4 and rec["id"] == info["id"]
    asc = platform.recorder.export(info["id"], "asc")
    imported = platform.recorder.import_text(asc, "imp", filename="x.asc")
    assert imported["frames"] == info["frames"]
    platform.trace.clear()
    r = await platform.recorder.replay(info["id"], mode="trace", speed=10)
    await asyncio.sleep(0.3)
    assert platform.recorder.replays[r["id"]]["state"] == "finished"
    assert len(platform.trace.frames) == info["frames"]
    # Replay auf den Bus: nur Tx-Frames → das Testdouble antwortet erneut
    platform.trace.clear()
    r = await platform.recorder.replay(info["id"], mode="bus", speed=5)
    await asyncio.sleep(0.4)
    assert platform.recorder.replays[r["id"]]["state"] == "finished"
    assert any(f["dir"] == "rx" for f in platform.trace.frames)
