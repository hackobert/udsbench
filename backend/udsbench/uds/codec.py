"""UDS-Request-Validierung und Response-Dekodierung (ISO 14229-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..catalogs.models import decode_fields, dtc_display
from ..catalogs.view import EMPTY, CatalogView
from ..core.hexutil import to_hex
from .nrc import nrc_description, nrc_name
from .services import (
    SERVICE_BY_RESPONSE,
    SERVICES,
    SESSION_NAMES,
    decode_dtc_status,
    service_name,
    subfunction_name,
)

NEGATIVE_RESPONSE_SID = 0x7F
SPRM_BIT = 0x80


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suppress_positive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "suppress_positive": self.suppress_positive,
        }


def is_suppress_positive(payload: bytes) -> bool:
    if len(payload) < 2:
        return False
    s = SERVICES.get(payload[0])
    return bool(s and s.has_subfunction and s.sprm_allowed and payload[1] & SPRM_BIT)


def validate_request(payload: bytes, *, strict: bool = True) -> ValidationResult:
    """Prüft eine Anfrage vor dem Senden. ``strict=False`` wandelt Fehler in Warnungen um."""
    errors: list[str] = []
    warnings: list[str] = []
    if not payload:
        return ValidationResult(False, ["Leere Nutzlast"])
    sid = payload[0]
    svc = SERVICES.get(sid)
    sprm = False
    if svc is None:
        if (sid & 0x40 and (sid - 0x40) in SERVICES) or sid == NEGATIVE_RESPONSE_SID:
            warnings.append(f"0x{sid:02X} ist eine Response-SID, kein Request")
        else:
            warnings.append(f"SID 0x{sid:02X} ist nicht im Standardkatalog (herstellerspezifisch?)")
        return ValidationResult(True, [], warnings)
    n = len(payload)
    if n < svc.min_len:
        errors.append(f"{svc.name}: Mindestlänge {svc.min_len} Byte, erhalten {n}")
    if svc.exact_len is not None and n != svc.exact_len:
        errors.append(f"{svc.name}: Länge muss {svc.exact_len} Byte sein, erhalten {n}")
    if svc.has_subfunction and n >= 2:
        raw_sub = payload[1]
        sub = raw_sub & (0x3F if sid == 0x86 else 0x7F)
        if raw_sub & SPRM_BIT:
            if svc.sprm_allowed:
                sprm = True
            else:
                errors.append(
                    f"{svc.name}: suppressPosRspMsgIndicationBit ist für diesen Dienst nicht zulässig"
                )
        if svc.subfunctions and sub not in svc.subfunctions:
            if sid == 0x27 and sub in (0x00, 0x7F):
                errors.append("SecurityAccess: Subfunktion 0x00/0x7F ist reserviert")
            else:
                warnings.append(f"{svc.name}: Subfunktion 0x{sub:02X} nicht im Normkatalog")
        if sub in svc.sub_exact_len and n != svc.sub_exact_len[sub]:
            errors.append(
                f"{svc.name}/0x{sub:02X}: Länge muss {svc.sub_exact_len[sub]} Byte sein, erhalten {n}"
            )
        if sub in svc.sub_min_len and n < svc.sub_min_len[sub]:
            errors.append(f"{svc.name}/0x{sub:02X}: Mindestlänge {svc.sub_min_len[sub]} Byte")
        if sid == 0x27 and sub % 2 == 0 and n < 3:
            errors.append("SecurityAccess sendKey: Schlüssel fehlt")
    # dienstspezifische Formatprüfungen
    if sid == 0x22 and n >= 3 and (n - 1) % 2:
        errors.append("ReadDataByIdentifier: DIDs müssen je 2 Byte lang sein")
    if sid in (0x23, 0x3D) and n >= 2:
        alfid = payload[1]
        a_len, s_len = alfid & 0x0F, alfid >> 4
        if not a_len or not s_len:
            errors.append("addressAndLengthFormatIdentifier ungültig (Nibble = 0)")
        elif sid == 0x23 and n != 2 + a_len + s_len:
            errors.append(f"ReadMemoryByAddress: erwartete Länge {2 + a_len + s_len}")
        elif sid == 0x3D and n <= 2 + a_len + s_len:
            errors.append("WriteMemoryByAddress: dataRecord fehlt")
    if sid in (0x34, 0x35) and n >= 3:
        alfid = payload[2]
        a_len, s_len = alfid & 0x0F, alfid >> 4
        if not a_len or not s_len:
            errors.append("addressAndLengthFormatIdentifier ungültig (Nibble = 0)")
        elif n != 3 + a_len + s_len:
            errors.append(f"{svc.name}: erwartete Länge {3 + a_len + s_len} Byte")
    if not strict:
        warnings = errors + warnings
        errors = []
    return ValidationResult(not errors, errors, warnings, sprm)


# --------------------------------------------------------------------------------------------
# Response-Dekodierung
# --------------------------------------------------------------------------------------------


def classify_payload(payload: bytes) -> str:
    """'request' | 'positive' | 'negative' | 'unknown'"""
    if not payload:
        return "unknown"
    sid = payload[0]
    if sid == NEGATIVE_RESPONSE_SID:
        return "negative"
    if sid in SERVICES:
        return "request"
    if sid in SERVICE_BY_RESPONSE:
        return "positive"
    if 0x10 <= sid <= 0x3E or 0x80 <= sid <= 0xBE:
        return "request"
    if 0x50 <= sid <= 0x7E or 0xC0 <= sid <= 0xFE:
        return "positive"
    return "unknown"


def _dtc_list(data: bytes, catalogs: CatalogView, record_len: int = 4) -> list[dict[str, Any]]:
    out = []
    for i in range(0, len(data) - record_len + 1, record_len):
        code = int.from_bytes(data[i : i + 3], "big")
        status = data[i + 3] if record_len >= 4 else 0
        d = catalogs.dtcs.get(code)
        out.append(
            {
                "code": code,
                "code_hex": f"{code:06X}",
                "display": dtc_display(code),
                "status": status,
                "status_hex": f"{status:02X}",
                "status_bits": decode_dtc_status(status),
                "name": d.name if d else None,
                "description": d.description if d else None,
            }
        )
    return out


def decode_did_records(data: bytes, requested: list[int], catalogs: CatalogView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pos = 0
    while pos + 2 <= len(data):
        did = int.from_bytes(data[pos : pos + 2], "big")
        pos += 2
        d = catalogs.did(did)
        if d and d.length is not None:
            raw = data[pos : pos + d.length]
        else:
            # Länge unbekannt: bis zum nächsten angefragten DID oder Ende
            nxt = len(data)
            rest = [r for r in requested if r != did]
            for r in rest:
                idx = data.find(r.to_bytes(2, "big"), pos)
                if idx != -1:
                    nxt = min(nxt, idx)
            raw = data[pos:nxt]
        pos += len(raw)
        rec: dict[str, Any] = {
            "did": did,
            "did_hex": f"0x{did:04X}",
            "raw": to_hex(raw),
            "name": d.name if d else None,
        }
        if d:
            try:
                rec["value"] = d.decode(raw)
                rec["unit"] = d.unit
            except Exception as exc:
                rec["decode_error"] = str(exc)
        out.append(rec)
    return out


def decode_response(
    response: bytes | None,
    request: bytes | None = None,
    catalogs: CatalogView | None = None,
) -> dict[str, Any]:
    cat = catalogs or EMPTY
    if not response:
        return {"type": "none", "text": "Keine Antwort"}
    sid = response[0]
    if sid == NEGATIVE_RESPONSE_SID:
        req_sid = response[1] if len(response) > 1 else None
        nrc = response[2] if len(response) > 2 else None
        out: dict[str, Any] = {
            "type": "negative",
            "request_sid": req_sid,
            "service": service_name(req_sid) if req_sid is not None else None,
            "nrc": nrc,
            "nrc_hex": f"0x{nrc:02X}" if nrc is not None else None,
            "nrc_name": nrc_name(nrc) if nrc is not None else None,
            "nrc_description": nrc_description(nrc) if nrc is not None else None,
        }
        if len(response) != 3:
            out["warning"] = f"Negative Response sollte 3 Byte lang sein (ist {len(response)})"
        if request and req_sid is not None and request[0] != req_sid:
            out["warning"] = "SID-Echo passt nicht zur Anfrage"
        out["text"] = f"NRC 0x{nrc or 0:02X} {out['nrc_name']} – {out['nrc_description']} ({out['service']})"
        return out
    svc = SERVICE_BY_RESPONSE.get(sid)
    if svc is None:
        kind = classify_payload(response)
        return {
            "type": kind,
            "sid": sid,
            "service": service_name(sid if kind == "request" else sid - 0x40),
            "data": to_hex(response[1:]),
            "text": f"{kind} 0x{sid:02X}",
        }
    out = {
        "type": "positive",
        "sid": sid,
        "request_sid": svc.sid,
        "service": svc.name,
        "data": to_hex(response[1:]),
    }
    if request and request[0] != svc.sid:
        out["warning"] = "Response-SID passt nicht zur Anfrage"
    fields: dict[str, Any] = {}
    d = response[1:]
    try:
        _decode_service_fields(svc.sid, d, request or b"", cat, fields)
    except Exception as exc:  # pragma: no cover - defensiv
        fields["decode_error"] = str(exc)
    if svc.has_subfunction and d:
        out["subfunction"] = d[0]
        out["subfunction_name"] = subfunction_name(svc.sid, d[0])
    out["fields"] = fields
    out["text"] = f"Positive Response {svc.name}" + (
        f" ({out.get('subfunction_name')})" if out.get("subfunction_name") else ""
    )
    return out


def _decode_service_fields(sid: int, d: bytes, req: bytes, cat: CatalogView, f: dict[str, Any]) -> None:
    if sid == 0x10 and d:
        f["session"] = d[0]
        f["session_name"] = SESSION_NAMES.get(d[0], f"session 0x{d[0]:02X}")
        if len(d) >= 5:
            f["p2_server_max_ms"] = int.from_bytes(d[1:3], "big")
            f["p2_star_server_max_ms"] = int.from_bytes(d[3:5], "big") * 10
    elif sid == 0x11 and d:
        f["reset_type"] = d[0]
        if d[0] == 0x04 and len(d) > 1:
            f["power_down_time_s"] = d[1]
    elif sid == 0x27 and d:
        level = d[0]
        f["level"] = level
        if level % 2:
            f["seed"] = to_hex(d[1:])
            f["seed_len"] = len(d) - 1
            f["already_unlocked"] = len(d) > 1 and not any(d[1:])
    elif sid == 0x22:
        requested = [int.from_bytes(req[i : i + 2], "big") for i in range(1, len(req) - 1, 2)] if req else []
        f["records"] = decode_did_records(d, requested, cat)
    elif sid == 0x2E and len(d) >= 2:
        did = int.from_bytes(d[:2], "big")
        dd = cat.did(did)
        f.update({"did": did, "did_hex": f"0x{did:04X}", "name": dd.name if dd else None})
    elif sid == 0x2F and len(d) >= 2:
        did = int.from_bytes(d[:2], "big")
        dd = cat.did(did)
        f.update({"did": did, "did_hex": f"0x{did:04X}", "name": dd.name if dd else None})
        if len(d) > 2:
            f["io_control_parameter"] = d[2]
            f["control_status"] = to_hex(d[3:])
            if dd and len(d) > 3:
                try:
                    f["value"] = dd.decode(d[3:])
                except Exception:
                    pass
    elif sid == 0x19 and d:
        sub = d[0]
        f["report_type"] = sub
        if sub in (0x01, 0x07) and len(d) >= 5:
            f.update(
                {
                    "status_availability_mask": d[1],
                    "dtc_format": d[2],
                    "dtc_count": int.from_bytes(d[3:5], "big"),
                }
            )
        elif sub in (0x02, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x15, 0x17) and len(d) >= 2:
            off = 3 if sub == 0x17 else 2
            f["status_availability_mask"] = d[1] if sub != 0x17 else d[2]
            f["dtcs"] = _dtc_list(d[off:], cat)
        elif sub in (0x04, 0x06, 0x18, 0x19) and len(d) >= 5:
            off = 2 if sub in (0x18, 0x19) else 1
            code = int.from_bytes(d[off : off + 3], "big")
            f["dtc"] = _dtc_list(d[off : off + 4], cat)[0] if len(d) >= off + 4 else {"code": code}
            f["records"] = to_hex(d[off + 4 :])
        elif sub == 0x14:
            f["dtcs"] = [
                {
                    "code": int.from_bytes(d[i : i + 3], "big"),
                    "display": dtc_display(int.from_bytes(d[i : i + 3], "big")),
                    "fault_detection_counter": d[i + 3],
                }
                for i in range(1, len(d) - 3, 4)
            ]
        elif sub == 0x03:
            f["snapshots"] = [
                {"code": int.from_bytes(d[i : i + 3], "big"), "record": d[i + 3]}
                for i in range(1, len(d) - 3, 4)
            ]
        else:
            f["raw"] = to_hex(d[1:])
    elif sid == 0x31 and len(d) >= 3:
        rid = int.from_bytes(d[1:3], "big")
        r = cat.routines.get(rid)
        f.update({"control_type": d[0], "rid": rid, "rid_hex": f"0x{rid:04X}", "name": r.name if r else None})
        status = d[3:]
        f["status_record"] = to_hex(status)
        if r and r.result_fields and status:
            f["results"] = decode_fields(r.result_fields, status)
    elif sid in (0x34, 0x35) and d:
        n = d[0] >> 4
        f["length_format_identifier"] = d[0]
        f["max_number_of_block_length"] = int.from_bytes(d[1 : 1 + n], "big") if n else None
    elif sid == 0x36 and d:
        f["block_sequence_counter"] = d[0]
        f["data"] = to_hex(d[1:])
    elif sid == 0x37:
        f["transfer_response_parameter"] = to_hex(d)
    elif sid in (0x23, 0x24):
        f["data"] = to_hex(d)
    elif sid == 0x28 and d:
        f["control_type"] = d[0]
    elif sid == 0x85 and d:
        f["setting_type"] = d[0]
    elif sid == 0x3E and d:
        f["zero_subfunction"] = d[0]
    elif sid == 0x2C and d:
        f["definition_type"] = d[0]
        if len(d) >= 3:
            f["did"] = int.from_bytes(d[1:3], "big")
    elif sid == 0x2A:
        f["data"] = to_hex(d)
    elif sid == 0x38 and d:
        f["mode_of_operation"] = d[0]
        f["data"] = to_hex(d[1:])
    elif sid in (0x83, 0x86, 0x87, 0x29) and d:
        f["data"] = to_hex(d[1:])


def describe_payload(payload: bytes, catalogs: CatalogView | None = None) -> str:
    """Einzeilige Klartextbeschreibung für den Trace."""
    if not payload:
        return ""
    cat = catalogs or EMPTY
    kind = classify_payload(payload)
    sid = payload[0]
    if kind == "negative":
        return decode_response(payload, None, cat)["text"]
    if kind == "positive":
        dec = decode_response(payload, None, cat)
        extra = ""
        fl = dec.get("fields", {})
        if "records" in fl and isinstance(fl["records"], list):
            extra = ", ".join(
                f"{r.get('name') or r['did_hex']}={r.get('value', r['raw'])}" for r in fl["records"]
            )
        elif "seed" in fl:
            extra = "Seed empfangen"
        elif fl.get("name"):
            extra = str(fl["name"])
        elif "dtcs" in fl:
            extra = f"{len(fl['dtcs'])} DTC(s)"
        elif "session_name" in fl:
            extra = fl["session_name"]
        return (
            f"+ {dec.get('service')}"
            + (f" [{dec.get('subfunction_name')}]" if dec.get("subfunction_name") else "")
            + (f": {extra}" if extra else "")
        )
    if kind == "request":
        name = service_name(sid)
        parts = [name]
        svc = SERVICES.get(sid)
        if svc and svc.has_subfunction and len(payload) > 1:
            sn = subfunction_name(sid, payload[1])
            parts.append(
                f"[{sn or f'0x{payload[1] & 0x7F:02X}'}{' SPRM' if payload[1] & 0x80 and svc.sprm_allowed else ''}]"
            )
        if sid in (0x22, 0x2E, 0x2F, 0x24) and len(payload) >= 3:
            dids = [
                int.from_bytes(payload[i : i + 2], "big")
                for i in range(1, 3 if sid != 0x22 else len(payload) - 1, 2)
            ]
            parts.append(", ".join((cat.did(x).name if cat.did(x) else f"0x{x:04X}") for x in dids))  # type: ignore[union-attr]
        if sid == 0x31 and len(payload) >= 4:
            rid = int.from_bytes(payload[2:4], "big")
            r = cat.routines.get(rid)
            parts.append(r.name if r else f"RID 0x{rid:04X}")
        return " ".join(parts)
    return f"0x{sid:02X}"
