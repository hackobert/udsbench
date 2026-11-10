"""ISO-TP-Transport: Segmentierung, Flow Control, BS, STmin (inkl. µs), Timeouts, Fehlerfälle."""

from __future__ import annotations

import asyncio
import time

import pytest

from udsbench.can.frame import CanFrame
from udsbench.isotp.codec import IsoTpError
from udsbench.isotp.profile import IsoTpProfile
from udsbench.isotp.transport import IsoTpTimeout, IsoTpTransport

pytestmark = pytest.mark.conformance


def profiles(**kw: object) -> tuple[IsoTpProfile, IsoTpProfile]:
    base: dict[str, object] = {"tx_id": 0x700, "rx_id": 0x708, "timeouts": {"n_bs": 200, "n_cr": 200}}
    base.update(kw)
    tester = IsoTpProfile.model_validate(base)
    return tester, tester.mirrored()


@pytest.mark.parametrize("n", [1, 7, 8, 50, 300, 4095])
async def test_transfer_both_directions(bus_pair, n: int):
    a, b = bus_pair
    pt, pe = profiles(block_size=4)
    ta, tb = IsoTpTransport(a, pt), IsoTpTransport(b, pe)
    ta.start()
    tb.start()
    payload = bytes(i & 0xFF for i in range(n))
    await ta.send(payload)
    msg = await tb.receive(1)
    assert msg.payload == payload
    await tb.send(payload[::-1])
    assert (await ta.receive(1)).payload == payload[::-1]


async def test_block_size_triggers_multiple_flow_controls(bus_pair):
    a, b = bus_pair
    pt, pe = profiles()
    pe = pe.model_copy(update={"block_size": 3})
    fcs: list[bytes] = []
    a.add_listener(lambda f: fcs.append(f.data) if f.direction == "rx" and f.data[0] >> 4 == 3 else None)
    ta, tb = IsoTpTransport(a, pt), IsoTpTransport(b, pe)
    ta.start()
    tb.start()
    await ta.send(bytes(6 + 7 * 10))  # FF + 10 CF → BS 3 → FC nach FF, CF3, CF6, CF9
    assert len((await tb.receive(1)).payload) == 76
    assert len(fcs) == 4
    assert all(fc[1] == 3 for fc in fcs)


async def test_stmin_microseconds_and_ms_respected(bus_pair):
    a, b = bus_pair
    pt, pe = profiles()
    stamps: list[float] = []
    b.add_listener(lambda f: stamps.append(time.perf_counter()) if f.data[0] >> 4 == 2 else None)
    ta, tb = IsoTpTransport(a, pt), IsoTpTransport(b, pe.model_copy(update={"st_min": 0x0A}))
    ta.start()
    tb.start()
    await ta.send(bytes(6 + 7 * 5))
    await tb.receive(1)
    gaps = [y - x for x, y in zip(stamps, stamps[1:], strict=False)]
    assert all(g >= 0.0095 for g in gaps), gaps
    # µs-Bereich (0xF5 = 500 µs) wird akzeptiert und eingehalten
    stamps.clear()
    tb.profile = tb.profile.model_copy(update={"st_min": 0xF5})
    await ta.send(bytes(6 + 7 * 5))
    await tb.receive(1)
    gaps = [y - x for x, y in zip(stamps, stamps[1:], strict=False)]
    assert all(g >= 0.0004 for g in gaps), gaps


async def test_n_bs_timeout_without_flow_control(bus_pair):
    a, _ = bus_pair
    pt, _ = profiles()
    ta = IsoTpTransport(a, pt)
    ta.start()
    t0 = time.perf_counter()
    with pytest.raises(IsoTpTimeout) as ei:
        await ta.send(bytes(20))
    assert ei.value.timer == "N_Bs"
    assert 0.18 < time.perf_counter() - t0 < 1.0


async def test_flow_control_wait_and_overflow(bus_pair):
    a, b = bus_pair
    pt, _ = profiles(wft_max=2)
    ta = IsoTpTransport(a, pt)
    ta.start()

    async def ecu_fc(statuses: list[int]) -> None:
        seen = asyncio.Event()
        b.add_listener(lambda f: seen.set() if f.data[0] >> 4 == 1 else None)
        await seen.wait()
        for st in statuses:
            await b.send(CanFrame(0x708, bytes([0x30 | st, 0, 0, 0, 0, 0, 0, 0])))
            await asyncio.sleep(0.01)

    task = asyncio.create_task(ecu_fc([1, 1, 1]))
    with pytest.raises(IsoTpError) as ei:
        await ta.send(bytes(20))
    assert ei.value.kind == "wft_ovrn"
    await task
    task = asyncio.create_task(ecu_fc([2]))
    with pytest.raises(IsoTpError) as ei:
        await ta.send(bytes(20))
    assert ei.value.kind == "overflow"
    await task


async def test_receiver_sends_overflow_for_too_long_message(bus_pair):
    a, b = bus_pair
    pt, pe = profiles()
    tb = IsoTpTransport(b, pe.model_copy(update={"max_rx_length": 10}))
    tb.start()
    got: list[bytes] = []
    a.add_listener(lambda f: got.append(f.data) if f.direction == "rx" else None)
    await a.send(CanFrame(0x700, bytes([0x10, 50, 1, 2, 3, 4, 5, 6])))
    await asyncio.sleep(0.05)
    assert got and got[0][0] == 0x32  # FC.OVFLW


async def test_n_cr_timeout_and_sequence_error(bus_pair):
    a, b = bus_pair
    _, pe = profiles()
    tb = IsoTpTransport(b, pe)
    tb.start()
    await a.send(CanFrame(0x700, bytes([0x10, 20, 1, 2, 3, 4, 5, 6])))
    await asyncio.sleep(0.3)  # kein CF → N_Cr
    assert any(e["kind"] == "error.timeout" and e["timer"] == "N_Cr" for e in tb.errors)
    await a.send(CanFrame(0x700, bytes([0x10, 20, 1, 2, 3, 4, 5, 6])))
    await asyncio.sleep(0.01)
    await a.send(CanFrame(0x700, bytes([0x22, 7, 8, 9, 10, 11, 12, 13])))  # falsche SN
    await asyncio.sleep(0.01)
    assert any(e["kind"] == "error.sequence" for e in tb.errors)
    with pytest.raises(IsoTpTimeout):
        await tb.receive(0.05)


async def test_unexpected_sf_aborts_reception(bus_pair):
    a, b = bus_pair
    _, pe = profiles()
    tb = IsoTpTransport(b, pe)
    tb.start()
    await a.send(CanFrame(0x700, bytes([0x10, 20, 1, 2, 3, 4, 5, 6])))
    await asyncio.sleep(0.01)
    await a.send(CanFrame(0x700, bytes([0x02, 0x3E, 0x00, 0, 0, 0, 0, 0])))
    msg = await tb.receive(0.2)
    assert msg.payload == b"\x3e\x00"
    assert any(e["kind"] == "error.unexpected" for e in tb.errors)


async def test_29bit_and_extended_addressing_filter(bus_pair):
    a, b = bus_pair
    pt, pe = profiles(
        tx_id=0x18DA10F1,
        rx_id=0x18DAF110,
        extended_id=True,
        addressing="extended",
        tx_address_extension=0x10,
        rx_address_extension=0xF1,
    )
    ta, tb = IsoTpTransport(a, pt), IsoTpTransport(b, pe)
    ta.start()
    tb.start()
    await ta.send(bytes(range(30)))
    assert (await tb.receive(1)).payload == bytes(range(30))
    # Frames mit falschem Adressbyte werden ignoriert
    await b.send(CanFrame(0x18DAF110, bytes([0x99, 0x02, 0x50, 0x01, 0, 0, 0, 0]), is_extended_id=True))
    with pytest.raises(IsoTpTimeout):
        await ta.receive(0.05)


async def test_can_fd_transfer(bus_pair):
    a, b = bus_pair
    pt, pe = profiles(can_fd=True, fd_tx_dl=64, dlc_mode="minimal")
    ta, tb = IsoTpTransport(a, pt), IsoTpTransport(b, pe)
    ta.start()
    tb.start()
    for n in (5, 40, 62, 1000):
        await ta.send(bytes(n))
        assert len((await tb.receive(1)).payload) == n
