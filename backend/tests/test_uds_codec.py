"""UDS-Katalog, Request-Validierung, Response-Dekodierung, NRC-Tabelle."""

from __future__ import annotations

import pytest

from udsbench.catalogs.models import DidDef, DtcDef
from udsbench.catalogs.view import CatalogView
from udsbench.uds.codec import (
    classify_payload,
    decode_response,
    describe_payload,
    is_suppress_positive,
    validate_request,
)
from udsbench.uds.nrc import NRC_TABLE, nrc_name, parse_nrc
from udsbench.uds.services import SERVICES, decode_dtc_status

pytestmark = pytest.mark.conformance

REQUIRED = [
    0x10,
    0x11,
    0x14,
    0x19,
    0x22,
    0x23,
    0x24,
    0x27,
    0x28,
    0x2A,
    0x2C,
    0x2E,
    0x2F,
    0x31,
    0x34,
    0x35,
    0x36,
    0x37,
    0x38,
    0x3D,
    0x3E,
    0x83,
    0x84,
    0x85,
    0x86,
    0x87,
]


def test_service_catalog_complete():
    for sid in REQUIRED:
        assert sid in SERVICES, hex(sid)
        assert SERVICES[sid].response_sid == sid + 0x40


def test_nrc_table_complete():
    expected = {
        0x10,
        0x11,
        0x12,
        0x13,
        0x14,
        0x21,
        0x22,
        0x24,
        0x25,
        0x26,
        0x31,
        0x33,
        0x34,
        0x35,
        0x36,
        0x37,
        0x38,
        0x39,
        0x3A,
        0x70,
        0x71,
        0x72,
        0x73,
        0x78,
        0x7E,
        0x7F,
        *range(0x81, 0x8E),
        *range(0x8F, 0x95),
        *range(0x50, 0x5E),
    }
    assert expected <= set(NRC_TABLE)
    assert nrc_name(0xF5) == "vehicleManufacturerSpecificConditionsNotCorrect"
    assert nrc_name(0xA0) == "reservedForSpecificConditionsNotCorrect"
    assert parse_nrc("invalidKey") == 0x35 and parse_nrc("0x78") == 0x78


@pytest.mark.parametrize(
    ("hexs", "ok"),
    [
        ("1003", True),
        ("10", False),
        ("100301", False),
        ("1083", True),
        ("2201", False),
        ("22F190", True),
        ("22F190F1", False),
        ("22F190F191", True),
        ("2701", True),
        ("2702", False),
        ("270211", True),
        ("2700", False),
        ("1980", False),  # SPRM für 0x19 nicht zulässig
        ("190209", True),
        ("1902", False),
        ("190A", True),
        ("3E00", True),
        ("3E80", True),
        ("3E0000", False),
        ("23 12 1000 10", True),
        ("23 12 1000", False),
        ("23 00 10", False),
        ("34 00 44 00001000 00000100", True),
        ("34 00 44 0000", False),
        ("280301", True),
        ("2804", False),
        ("2E F1 90", False),
        ("31 01 FF", False),
        ("31 01 FF 00", True),
    ],
)
def test_validate_request(hexs: str, ok: bool):
    v = validate_request(bytes.fromhex(hexs.replace(" ", "")))
    assert v.ok == ok, v.errors


def test_sprm_detection():
    assert is_suppress_positive(bytes.fromhex("3E80"))
    assert is_suppress_positive(bytes.fromhex("1083"))
    assert not is_suppress_positive(bytes.fromhex("3E00"))
    assert not is_suppress_positive(bytes.fromhex("1981"))
    assert validate_request(bytes.fromhex("3E80")).suppress_positive


def test_validation_warn_mode():
    v = validate_request(bytes.fromhex("10"), strict=False)
    assert v.ok and v.warnings


def test_classify():
    assert classify_payload(bytes.fromhex("22F190")) == "request"
    assert classify_payload(bytes.fromhex("62F190")) == "positive"
    assert classify_payload(bytes.fromhex("7F2231")) == "negative"


def test_decode_negative():
    d = decode_response(bytes.fromhex("7F2733"), bytes.fromhex("2701"))
    assert d["type"] == "negative" and d["nrc"] == 0x33 and d["nrc_name"] == "securityAccessDenied"
    assert d["service"] == "SecurityAccess"


def test_decode_session_timing():
    d = decode_response(bytes.fromhex("5003003201F4"), bytes.fromhex("1003"))
    f = d["fields"]
    assert f["session"] == 3 and f["p2_server_max_ms"] == 50 and f["p2_star_server_max_ms"] == 5000
    assert d["subfunction_name"] == "extendedDiagnosticSession"


def test_decode_did_with_catalog():
    cat = CatalogView(
        dids={
            0x0100: DidDef(id=0x0100, name="voltage", type="uint", length=2, scale=0.001, unit="V"),
            0xF100: DidDef(id=0xF100, name="ident", type="ascii", length=4),
        }
    )
    d = decode_response(bytes.fromhex("6201003138F10041424344"), bytes.fromhex("220100F100"), cat)
    recs = d["fields"]["records"]
    assert recs[0]["value"] == pytest.approx(12.6) and recs[0]["unit"] == "V"
    assert recs[1]["value"] == "ABCD"
    assert "voltage=12.6" in describe_payload(bytes.fromhex("6201003138F10041424344"), cat)


def test_decode_dtcs():
    cat = CatalogView(dtcs={0x012345: DtcDef(code=0x012345, name="demo")})
    d = decode_response(bytes.fromhex("5902FF01234509C1000024"), bytes.fromhex("1902FF"), cat)
    dtcs = d["fields"]["dtcs"]
    assert len(dtcs) == 2 and dtcs[0]["name"] == "demo" and dtcs[0]["status_bits"]["confirmedDTC"]
    assert dtcs[1]["display"].startswith("U")
    assert decode_dtc_status(0x09) == {
        **{k: False for k in decode_dtc_status(0)},
        "testFailed": True,
        "confirmedDTC": True,
    }


def test_decode_seed_and_transfer():
    assert decode_response(bytes.fromhex("6701AABBCCDD"))["fields"]["seed"] == "AA BB CC DD"
    assert decode_response(bytes.fromhex("67010000"))["fields"]["already_unlocked"] is True
    assert decode_response(bytes.fromhex("74200102"))["fields"]["max_number_of_block_length"] == 0x102


def test_describe_requests():
    assert describe_payload(bytes.fromhex("1003")).startswith(
        "DiagnosticSessionControl [extendedDiagnosticSession"
    )
    assert "SPRM" in describe_payload(bytes.fromhex("3E80"))
    assert "NRC 0x35" in describe_payload(bytes.fromhex("7F2735"))
