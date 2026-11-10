"""Konformität ISO 15765-2: PCI-/Längenbyte je Adressierungsmodus, Padding, Round-Trip."""

from __future__ import annotations

import itertools

import pytest

from udsbench.isotp.codec import (
    IsoTpError,
    PciType,
    decode_frames,
    encode_flow_control,
    encode_message,
    parse_frame,
    preview_frames,
    seconds_to_stmin,
    stmin_to_seconds,
)
from udsbench.isotp.profile import IsoTpProfile

pytestmark = pytest.mark.conformance


def prof(**kw: object) -> IsoTpProfile:
    base: dict[str, object] = {"tx_id": 0x700, "rx_id": 0x708}
    base.update(kw)
    return IsoTpProfile.model_validate(base)


# ------------------------------------------------------------------------------------------
# PCI-Position je Adressierungsmodus
# ------------------------------------------------------------------------------------------


def test_normal_sf_pci_in_byte0_with_padding_ff():
    p = prof(padding={"enabled": True, "byte": 0xFF}, dlc_mode="fixed")
    (frame,) = encode_message(bytes.fromhex("22F190"), p)
    assert frame == bytes.fromhex("0322F190FFFFFFFF")
    assert len(frame) == 8


@pytest.mark.parametrize("mode", ["extended", "mixed"])
def test_extended_and_mixed_sf_length_in_byte1(mode: str):
    p = prof(addressing=mode, tx_address_extension=0x2B, padding={"enabled": True, "byte": 0xAA})
    (frame,) = encode_message(bytes.fromhex("22F190"), p)
    assert frame[0] == 0x2B  # Adress-Erweiterung
    assert frame[1] == 0x03  # PCI/Länge im zweiten Byte
    assert frame[2:5] == bytes.fromhex("22F190")
    assert frame[5:] == b"\xaa\xaa\xaa"
    info = parse_frame(frame, mode)
    assert info.pci_offset == 1 and info.length == 3 and info.address_extension == 0x2B


def test_sf_capacity_classic():
    assert len(encode_message(bytes(7), prof())) == 1
    assert len(encode_message(bytes(8), prof())) == 2
    ext = prof(addressing="extended", tx_address_extension=0x10)
    assert len(encode_message(bytes(6), ext)) == 1
    assert len(encode_message(bytes(7), ext)) == 2


def test_first_frame_12bit_length_counts_total_message():
    payload = bytes(range(20))
    frames = encode_message(payload, prof())
    ff = frames[0]
    assert ff[0] == 0x10 and ff[1] == 20  # FF_DL = Gesamtlänge
    assert ff[2:8] == payload[:6]
    assert frames[1][0] == 0x21 and frames[2][0] == 0x22
    ext = prof(addressing="extended", tx_address_extension=0x55)
    ff = encode_message(payload, ext)[0]
    assert ff[0] == 0x55 and ff[1] == 0x10 and ff[2] == 20 and ff[3:8] == payload[:5]


def test_first_frame_escape_for_large_messages():
    payload = bytes(5000)
    ff = encode_message(payload, prof())[0]
    assert ff[:2] == b"\x10\x00" and int.from_bytes(ff[2:6], "big") == 5000
    assert decode_frames(encode_message(payload, prof())) == payload


def test_sequence_numbers_wrap():
    frames = encode_message(bytes(200), prof())
    seqs = [f[0] & 0x0F for f in frames[1:]]
    assert seqs[:16] == [*range(1, 16), 0]
    assert all(f[0] >> 4 == 2 for f in frames[1:])


# ------------------------------------------------------------------------------------------
# Padding / DLC
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("pad_byte", [0x00, 0xAA, 0xFF])
def test_padding_fixed_dlc_fills_all_frames(pad_byte: int):
    p = prof(padding={"enabled": True, "byte": pad_byte}, dlc_mode="fixed")
    frames = encode_message(bytes(range(1, 11)), p)
    assert all(len(f) == 8 for f in frames)
    last = frames[-1]
    # FF trägt 6, CF1 trägt 4 Nutzdatenbytes → 3 Padding-Bytes
    assert last[:5] == bytes([0x21, 7, 8, 9, 10]) and last[5:] == bytes([pad_byte]) * 3


def test_padding_disabled_minimal_dlc():
    p = prof(padding={"enabled": False}, dlc_mode="minimal")
    (sf,) = encode_message(bytes.fromhex("3E00"), p)
    assert sf == bytes.fromhex("023E00")
    frames = encode_message(bytes(range(1, 11)), p)
    assert len(frames[0]) == 8 and frames[-1] == bytes([0x21, 7, 8, 9, 10])
    assert encode_flow_control(0, 0, 0, p) == b"\x30\x00\x00"


def test_padding_enabled_minimal_dlc_classic_is_unpadded():
    p = prof(padding={"enabled": True, "byte": 0xFF}, dlc_mode="minimal")
    assert encode_message(b"\x10\x03", p) == [b"\x02\x10\x03"]


def test_flow_control_padding():
    p = prof(padding={"enabled": True, "byte": 0xFF})
    assert encode_flow_control(0, 8, 0x14, p) == bytes.fromhex("30081 4FFFFFFFFFF".replace(" ", ""))
    e = prof(addressing="extended", tx_address_extension=0xF1, padding={"enabled": True, "byte": 0x00})
    assert encode_flow_control(1, 0, 0, e) == bytes.fromhex("F131000000000000")


def test_receive_ignores_padding_via_pci_length():
    info = parse_frame(bytes.fromhex("037F2278CCCCCCCC"))
    assert info.pci_type == PciType.SF and info.data == bytes.fromhex("7F2278") and info.padding == 4


# ------------------------------------------------------------------------------------------
# CAN-FD
# ------------------------------------------------------------------------------------------


def test_fd_escape_single_frame_and_dlc_steps():
    p = prof(can_fd=True, fd_tx_dl=64, padding={"enabled": True, "byte": 0xCC}, dlc_mode="minimal")
    (sf,) = encode_message(bytes(20), p)
    assert sf[0] == 0x00 and sf[1] == 20  # Escape-SF: SF_DL im Folgebyte
    assert len(sf) == 24  # nächste gültige FD-Länge (22 → 24)
    assert sf[22:] == b"\xcc\xcc"
    (small,) = encode_message(b"\x3e\x00", p)
    assert small == b"\x02\x3e\x00"


def test_fd_fixed_uses_escape_when_can_dl_gt_8():
    p = prof(can_fd=True, fd_tx_dl=64, padding={"enabled": True, "byte": 0xCC}, dlc_mode="fixed")
    (sf,) = encode_message(b"\x3e\x00", p)
    assert len(sf) == 64 and sf[:4] == b"\x00\x02\x3e\x00"


def test_fd_multi_frame_roundtrip():
    p = prof(can_fd=True, fd_tx_dl=64, padding={"enabled": True, "byte": 0xCC}, dlc_mode="minimal")
    payload = bytes(range(256)) * 2
    frames = encode_message(payload, p)
    assert len(frames[0]) == 64 and frames[0][:2] == bytes([0x12, 0x00])
    assert decode_frames(frames) == payload


# ------------------------------------------------------------------------------------------
# Round-Trip über alle Profilvarianten
# ------------------------------------------------------------------------------------------

LENGTHS = [1, 2, 6, 7, 8, 13, 62, 63, 100, 4095, 4096]
VARIANTS = list(
    itertools.product(
        ["normal", "extended", "mixed"],
        [(False, 0x00), (True, 0x00), (True, 0xAA), (True, 0xFF)],
        ["fixed", "minimal"],
        [False, True],
    )
)


@pytest.mark.parametrize(("addressing", "padding", "dlc_mode", "fd"), VARIANTS)
def test_roundtrip_all_profiles(addressing: str, padding: tuple[bool, int], dlc_mode: str, fd: bool):
    p = prof(
        addressing=addressing,
        tx_address_extension=0x33 if addressing != "normal" else None,
        padding={"enabled": padding[0], "byte": padding[1]},
        dlc_mode=dlc_mode,
        can_fd=fd,
        fd_tx_dl=64 if fd else 8,
    )
    for n in LENGTHS:
        payload = bytes((i * 7 + 3) & 0xFF for i in range(n))
        frames = encode_message(payload, p)
        assert decode_frames(frames, addressing) == payload, (n, frames[:2])
        for f in frames:
            assert len(f) <= p.tx_dl
            if addressing != "normal":
                assert f[0] == 0x33
            if padding[0] and dlc_mode == "fixed":
                assert len(f) == p.tx_dl
            if fd:
                assert len(f) in (0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64)
        # Padding-Bytes am Ende des letzten Frames tragen den konfigurierten Wert
        pv = preview_frames(payload, p)
        for fr in pv:
            for b, role in zip(fr.data, fr.roles, strict=True):
                if role == "pad":
                    assert b == (padding[1] if padding[0] else 0xCC) or not padding[0]


def test_functional_requires_single_frame():
    p = prof(functional_id=0x7DF)
    with pytest.raises(IsoTpError):
        encode_message(bytes(10), p, functional=True)
    (sf,) = encode_message(b"\x3e\x80", p, functional=True)
    assert sf[:3] == b"\x02\x3e\x80"


def test_functional_address_extension():
    p = prof(
        addressing="extended",
        tx_address_extension=0x10,
        functional_address_extension=0xFE,
        functional_id=0x7DF,
    )
    (sf,) = encode_message(b"\x3e\x80", p, functional=True)
    assert sf[0] == 0xFE and sf[1] == 0x02


# ------------------------------------------------------------------------------------------
# STmin und Fehlerfälle
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [
        (0x00, 0.0),
        (0x14, 0.020),
        (0x7F, 0.127),
        (0xF1, 100e-6),
        (0xF9, 900e-6),
        (0x80, 0.127),
        (0xF0, 0.127),
        (0xFA, 0.127),
    ],
)
def test_stmin(raw: int, seconds: float):
    assert stmin_to_seconds(raw) == pytest.approx(seconds)


def test_stmin_inverse():
    assert seconds_to_stmin(0.0005) == 0xF5
    assert seconds_to_stmin(0.010) == 0x0A
    assert seconds_to_stmin(1.0) == 0x7F


@pytest.mark.parametrize("raw", ["", "00", "0A0102", "40", "1000"])
def test_parse_errors(raw: str):
    with pytest.raises(IsoTpError):
        parse_frame(bytes.fromhex(raw))


def test_sequence_error_detected():
    frames = encode_message(bytes(20), prof())
    frames[2] = bytes([0x23]) + frames[2][1:]
    with pytest.raises(IsoTpError) as ei:
        decode_frames(frames)
    assert ei.value.kind == "sequence"


def test_profile_validation():
    with pytest.raises(ValueError):
        prof(addressing="extended")  # Adressbyte fehlt
    with pytest.raises(ValueError):
        prof(tx_id=0x800)  # passt nicht in 11 Bit
    assert prof(tx_id=0x18DA10F1, rx_id=0x18DAF110, extended_id=True).tx_id == 0x18DA10F1
    assert prof(tx_id="0x7E0", rx_id="7E8h").rx_id == 0x7E8


def test_preview_roles():
    p = prof(addressing="extended", tx_address_extension=0x2B, padding={"enabled": True, "byte": 0xFF})
    (fr,) = preview_frames(b"\x10\x03", p)
    assert fr.roles == ["ae", "pci", "data", "data", "pad", "pad", "pad", "pad"]
    assert "SF_DL=2" in fr.note
