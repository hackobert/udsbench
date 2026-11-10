"""ISO 15765-2 Frame-Codec (reine Funktionen, ohne I/O).

Längensemantik (eindeutig):

* **Single Frame (SF)**: ``SF_DL`` = Anzahl der *folgenden* UDS-Nutzdatenbytes.
  Klassisch: PCI ``0x0L`` (L = 1..7 normal, 1..6 extended/mixed).
  CAN-FD mit mehr Daten: Escape ``0x00 LL`` (SF_DL im Folgebyte).
* **First Frame (FF)**: ``FF_DL`` = *Gesamtlänge* der UDS-Nachricht, 12 Bit: ``0x1H LL``;
  Escape für > 4095 Byte: ``0x10 0x00`` + 32-Bit-Länge.
* **Consecutive Frame (CF)**: ``0x2N`` mit Sequenznummer N (1..15, dann 0..15 umlaufend).
* **Flow Control (FC)**: ``0x3S BS STmin`` (S: 0 CTS, 1 WAIT, 2 OVFLW).

Die PCI steht bei normaler Adressierung in Byte 0; bei extended/mixed Adressierung trägt Byte 0
die Adress-Erweiterung (N_TA bzw. N_AE) und die PCI steht in Byte 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from ..can.frame import next_fd_length
from .profile import IsoTpProfile


class IsoTpError(Exception):
    """Fehlerhafter Frame / Protokollfehler."""

    def __init__(self, message: str, kind: str = "protocol") -> None:
        super().__init__(message)
        self.kind = kind


class PciType(IntEnum):
    SF = 0
    FF = 1
    CF = 2
    FC = 3


class FlowStatus(IntEnum):
    CTS = 0
    WAIT = 1
    OVFLW = 2


PCI_NAMES = {PciType.SF: "SF", PciType.FF: "FF", PciType.CF: "CF", PciType.FC: "FC"}


# --------------------------------------------------------------------------------------------
# STmin
# --------------------------------------------------------------------------------------------


def stmin_to_seconds(raw: int) -> float:
    """STmin-Rohwert → Sekunden. Reservierte Werte werden wie 0x7F (127 ms) behandelt (ISO 15765-2)."""
    if 0x00 <= raw <= 0x7F:
        return raw / 1000.0
    if 0xF1 <= raw <= 0xF9:
        return (raw - 0xF0) * 100e-6
    return 0x7F / 1000.0


def stmin_to_text(raw: int) -> str:
    if 0x00 <= raw <= 0x7F:
        return f"{raw} ms"
    if 0xF1 <= raw <= 0xF9:
        return f"{(raw - 0xF0) * 100} µs"
    return "reserviert (→127 ms)"


def seconds_to_stmin(seconds: float) -> int:
    us = seconds * 1e6
    if us <= 0:
        return 0
    if us < 1000:
        return 0xF0 + max(1, min(9, round(us / 100)))
    return min(0x7F, round(us / 1000))


# --------------------------------------------------------------------------------------------
# Padding / DLC
# --------------------------------------------------------------------------------------------


def frame_target_length(raw_len: int, profile: IsoTpProfile) -> int:
    """Ziel-Datenlänge eines Frames abhängig von Padding und DLC-Modus.

    * Padding aktiv + DLC fixed  → immer TX_DL (8 bei klassischem CAN).
    * sonst klassisches CAN      → minimale Länge (kein Padding).
    * sonst CAN-FD               → nächste gültige FD-Länge (DLC-Stufe) mit Padding-Byte.
    """
    if profile.padding.enabled and profile.dlc_mode == "fixed":
        return profile.tx_dl
    if profile.can_fd and raw_len > 8:
        return next_fd_length(raw_len)
    return raw_len


def pad_frame(raw: bytes, profile: IsoTpProfile) -> bytes:
    target = frame_target_length(len(raw), profile)
    if len(raw) > profile.tx_dl:
        raise IsoTpError(f"Frame länger als TX_DL ({len(raw)} > {profile.tx_dl})")
    return raw + bytes([profile.padding.byte]) * (target - len(raw))


# --------------------------------------------------------------------------------------------
# Encoder
# --------------------------------------------------------------------------------------------


def _prefix(profile: IsoTpProfile, functional: bool = False) -> bytes:
    if profile.addressing == "normal":
        return b""
    ae = (
        profile.functional_address_extension
        if functional and profile.functional_address_extension is not None
        else profile.tx_address_extension
    )
    assert ae is not None
    return bytes([ae])


def sf_capacity(profile: IsoTpProfile) -> int:
    """Maximale Nutzdatenlänge eines Single Frames."""
    if profile.tx_dl <= 8:
        return 7 - profile.ae_len
    return profile.tx_dl - 2 - profile.ae_len


def encode_single_frame(payload: bytes, profile: IsoTpProfile, functional: bool = False) -> bytes | None:
    n = len(payload)
    if n == 0:
        raise IsoTpError("Leere Nutzlast kann nicht gesendet werden", "argument")
    prefix = _prefix(profile, functional)
    if n <= 7 - profile.ae_len:
        frame = pad_frame(prefix + bytes([n]) + payload, profile)
        # ISO 15765-2: Bei CAN_DL > 8 muss das Escape-Format (SF_DL im Folgebyte) verwendet werden.
        if len(frame) <= 8:
            return frame
    if profile.tx_dl > 8 and n <= sf_capacity(profile):
        return pad_frame(prefix + bytes([0x00, n]) + payload, profile)
    return None


def encode_first_frame(payload: bytes, profile: IsoTpProfile) -> tuple[bytes, int]:
    """Gibt (Frame, Anzahl verbrauchter Nutzdatenbytes) zurück."""
    n = len(payload)
    prefix = _prefix(profile)
    if n <= 0xFFF:
        pci = bytes([0x10 | (n >> 8), n & 0xFF])
    else:
        pci = bytes([0x10, 0x00]) + n.to_bytes(4, "big")
    head = prefix + pci
    take = profile.tx_dl - len(head)
    return head + payload[:take], take


def cf_capacity(profile: IsoTpProfile) -> int:
    return profile.tx_dl - 1 - profile.ae_len


def encode_consecutive_frame(chunk: bytes, seq: int, profile: IsoTpProfile) -> bytes:
    return pad_frame(_prefix(profile) + bytes([0x20 | (seq & 0x0F)]) + chunk, profile)


def encode_flow_control(status: int, block_size: int, st_min: int, profile: IsoTpProfile) -> bytes:
    return pad_frame(
        _prefix(profile) + bytes([0x30 | (status & 0x0F), block_size & 0xFF, st_min & 0xFF]), profile
    )


def encode_message(payload: bytes, profile: IsoTpProfile, functional: bool = False) -> list[bytes]:
    """Kodiert eine komplette Nachricht in Frames (ohne FC – für Vorschau/Round-Trip-Tests)."""
    sf = encode_single_frame(payload, profile, functional)
    if sf is not None:
        return [sf]
    if functional:
        raise IsoTpError("Funktionale Adressierung erlaubt nur Single Frames", "argument")
    ff, used = encode_first_frame(payload, profile)
    frames = [ff]
    seq = 1
    cap = cf_capacity(profile)
    pos = used
    while pos < len(payload):
        frames.append(encode_consecutive_frame(payload[pos : pos + cap], seq, profile))
        pos += cap
        seq = (seq + 1) & 0x0F
    return frames


# --------------------------------------------------------------------------------------------
# Decoder
# --------------------------------------------------------------------------------------------


@dataclass
class FrameInfo:
    pci_type: PciType
    address_extension: int | None
    pci_offset: int
    length: int | None = None  # SF_DL bzw. FF_DL
    seq: int | None = None
    flow_status: int | None = None
    block_size: int | None = None
    st_min: int | None = None
    data: bytes = b""  # Nutzdaten in diesem Frame (bei SF bereits auf SF_DL gekürzt)
    escape: bool = False
    padding: int = 0  # Anzahl Padding-Bytes (nur SF/FC eindeutig bestimmbar)
    header_len: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pci": PCI_NAMES[self.pci_type],
            "ae": self.address_extension,
            "pci_offset": self.pci_offset,
            "length": self.length,
            "seq": self.seq,
            "flow_status": self.flow_status,
            "bs": self.block_size,
            "st_min": self.st_min,
            "escape": self.escape,
            "padding": self.padding,
        }


def parse_frame(data: bytes, addressing: str = "normal") -> FrameInfo:
    ae_len = 0 if addressing == "normal" else 1
    if len(data) <= ae_len:
        raise IsoTpError("Frame zu kurz für PCI", "format")
    ae = data[0] if ae_len else None
    o = ae_len
    pci_byte = data[o]
    t = pci_byte >> 4
    if t == PciType.SF:
        sf_dl = pci_byte & 0x0F
        if sf_dl == 0:
            # Escape-SF (nur CAN-FD, CAN_DL > 8)
            if len(data) <= 8 or len(data) < o + 2:
                raise IsoTpError("SF_DL = 0 ist bei CAN_DL <= 8 ungültig", "format")
            sf_dl = data[o + 1]
            start = o + 2
            if sf_dl == 0 or start + sf_dl > len(data):
                raise IsoTpError(f"Ungültige Escape-SF-Länge {sf_dl}", "format")
            return FrameInfo(
                PciType.SF,
                ae,
                o,
                sf_dl,
                data=data[start : start + sf_dl],
                escape=True,
                padding=len(data) - start - sf_dl,
                header_len=start,
            )
        start = o + 1
        if start + sf_dl > len(data):
            raise IsoTpError(f"SF_DL {sf_dl} größer als verfügbare Daten", "format")
        return FrameInfo(
            PciType.SF,
            ae,
            o,
            sf_dl,
            data=data[start : start + sf_dl],
            padding=len(data) - start - sf_dl,
            header_len=start,
        )
    if t == PciType.FF:
        if len(data) < o + 2:
            raise IsoTpError("First Frame zu kurz", "format")
        ff_dl = ((pci_byte & 0x0F) << 8) | data[o + 1]
        start = o + 2
        escape = False
        if ff_dl == 0:
            if len(data) < o + 6:
                raise IsoTpError("Escape-First-Frame zu kurz", "format")
            ff_dl = int.from_bytes(data[o + 2 : o + 6], "big")
            start = o + 6
            escape = True
        return FrameInfo(PciType.FF, ae, o, ff_dl, data=data[start:], escape=escape, header_len=start)
    if t == PciType.CF:
        return FrameInfo(PciType.CF, ae, o, seq=pci_byte & 0x0F, data=data[o + 1 :], header_len=o + 1)
    if t == PciType.FC:
        if len(data) < o + 3:
            raise IsoTpError("Flow-Control-Frame zu kurz", "format")
        return FrameInfo(
            PciType.FC,
            ae,
            o,
            flow_status=pci_byte & 0x0F,
            block_size=data[o + 1],
            st_min=data[o + 2],
            padding=len(data) - o - 3,
            header_len=o + 3,
        )
    raise IsoTpError(f"Unbekannter PCI-Typ 0x{t:X}", "format")


def decode_frames(frames: list[bytes], addressing: str = "normal") -> bytes:
    """Setzt eine Frame-Folge (SF oder FF+CF…, FC werden ignoriert) wieder zur Nachricht zusammen."""
    payload = b""
    expected: int | None = None
    seq = 1
    for raw in frames:
        info = parse_frame(raw, addressing)
        if info.pci_type == PciType.FC:
            continue
        if info.pci_type == PciType.SF:
            return info.data
        if info.pci_type == PciType.FF:
            expected = info.length
            payload = info.data
            seq = 1
            continue
        if info.pci_type == PciType.CF:
            if expected is None:
                raise IsoTpError("CF ohne FF", "unexpected")
            if info.seq != seq:
                raise IsoTpError(f"Sequenzfehler: erwartet {seq}, erhalten {info.seq}", "sequence")
            payload += info.data[: expected - len(payload)]
            seq = (seq + 1) & 0x0F
            if len(payload) >= expected:
                return payload
    if expected is not None and len(payload) < expected:
        raise IsoTpError("Nachricht unvollständig", "incomplete")
    return payload


# --------------------------------------------------------------------------------------------
# Vorschau mit Byte-Rollen (für die UI)
# --------------------------------------------------------------------------------------------


@dataclass
class AnnotatedFrame:
    can_id: int
    extended_id: bool
    is_fd: bool
    data: bytes
    roles: list[str] = field(default_factory=list)  # je Byte: ae | pci | len | data | pad | fc
    kind: str = "SF"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_id": self.can_id,
            "can_id_hex": f"{self.can_id:08X}" if self.extended_id else f"{self.can_id:03X}",
            "extended_id": self.extended_id,
            "fd": self.is_fd,
            "dlc": len(self.data),
            "kind": self.kind,
            "note": self.note,
            "bytes": [{"value": f"{b:02X}", "role": r} for b, r in zip(self.data, self.roles, strict=False)],
        }


def annotate(raw: bytes, addressing: str) -> tuple[str, list[str], str]:
    info = parse_frame(raw, addressing)
    roles: list[str] = []
    if info.address_extension is not None:
        roles.append("ae")
    kind = PCI_NAMES[info.pci_type]
    note = ""
    if info.pci_type == PciType.SF:
        if info.escape:
            roles += ["pci", "len"]
        else:
            roles.append("pci")
        roles += ["data"] * len(info.data)
        note = f"SF_DL={info.length} (folgende Nutzdatenbytes)"
    elif info.pci_type == PciType.FF:
        roles += ["pci", "len"] + (["len"] * 4 if info.escape else [])
        roles += ["data"] * len(info.data)
        note = f"FF_DL={info.length} (Gesamtlänge der Nachricht)"
    elif info.pci_type == PciType.CF:
        roles.append("pci")
        note = f"SN={info.seq}"
    else:
        roles += ["pci", "fc", "fc"]
        note = f"FS={info.flow_status} BS={info.block_size} STmin={stmin_to_text(info.st_min or 0)}"
    roles += ["data"] * (len(raw) - len(roles))
    return kind, roles, note


def preview_frames(payload: bytes, profile: IsoTpProfile, functional: bool = False) -> list[AnnotatedFrame]:
    frames = encode_message(payload, profile, functional)
    can_id = profile.functional_id if functional and profile.functional_id is not None else profile.tx_id
    out: list[AnnotatedFrame] = []
    remaining = len(payload)
    for raw in frames:
        kind, roles, note = annotate(raw, profile.addressing)
        info = parse_frame(raw, profile.addressing)
        if info.pci_type == PciType.SF:
            used = info.length or 0
            data_start = info.header_len
        elif info.pci_type == PciType.FF:
            used = len(info.data)
            data_start = info.header_len
        else:
            used = min(remaining, len(info.data))
            data_start = info.header_len
        # Rollen der Padding-Bytes kennzeichnen
        for i in range(data_start + used, len(raw)):
            roles[i] = "pad"
        remaining -= used
        out.append(AnnotatedFrame(can_id, profile.extended_id, profile.can_fd, raw, roles, kind, note))
    return out
