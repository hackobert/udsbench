"""Kataloge (Kodierung/Dekodierung) und Konfig-/Paketvalidierung inkl. Kollisionserkennung."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from udsbench.catalogs.models import DidDef, ValueSpec, dtc_display
from udsbench.config.loader import load_package_file, parse_package
from udsbench.config.packages import PackageManager
from udsbench.core.errors import ConflictError, ValidationFailed

from .conftest import DEMO_PACKAGES


@pytest.mark.parametrize(
    ("spec", "raw", "value"),
    [
        ({"type": "uint", "length": 2}, "0102", 258),
        ({"type": "uint", "length": 2, "byteorder": "little"}, "0102", 513),
        ({"type": "int", "length": 1}, "FF", -1),
        ({"type": "uint", "length": 2, "scale": 0.1, "offset": -40}, "01F4", 10.0),
        ({"type": "ascii", "length": 4}, "41424344", "ABCD"),
        ({"type": "bcd", "length": 2}, "1234", "1234"),
        ({"type": "enum", "length": 1, "enum": {1: "on", 0: "off"}}, "01", "on"),
        ({"type": "bool", "length": 1}, "01", True),
        ({"type": "float32", "length": 4}, "3FC00000", 1.5),
        ({"type": "hex"}, "DEAD", "DE AD"),
    ],
)
def test_value_roundtrip(spec: dict, raw: str, value: object):
    vs = ValueSpec.model_validate(spec)
    assert vs.decode(bytes.fromhex(raw)) == value
    assert vs.encode(value) == bytes.fromhex(raw)


def test_bitfield():
    vs = ValueSpec.model_validate(
        {
            "type": "bitfield",
            "length": 1,
            "bits": [{"name": "a", "bit": 0}, {"name": "lvl", "bit": 4, "length": 2, "enum": {2: "high"}}],
        }
    )
    assert vs.decode(b"\x21") == {"a": 1, "lvl": "high"}
    assert vs.encode({"a": 1, "lvl": "high"}) == b"\x21"


def test_range_check_and_length():
    vs = ValueSpec(type="uint", length=2, min=0, max=100)
    with pytest.raises(ValueError):
        vs.encode(101)
    with pytest.raises(ValueError):
        ValueSpec(type="ascii", length=2).encode("ABC")
    with pytest.raises(ValueError):
        DidDef(id=0x10000, name="x")


def test_dtc_display():
    assert dtc_display(0x012345) == "P0123-45"
    assert dtc_display(0xC10000) == "U0100-00"


def test_demo_package_valid():
    pkg = load_package_file(DEMO_PACKAGES / "demo.example.yaml")
    assert pkg.package.id == "demo" and pkg.ecus and pkg.tests


def _demo_dict() -> dict:
    import yaml

    return yaml.safe_load((DEMO_PACKAGES / "demo.example.yaml").read_text(encoding="utf-8"))


def test_package_validation_errors_are_descriptive():
    d = _demo_dict()
    d["ecus"][0]["isotp"] = "missing_profile"
    with pytest.raises(ValidationFailed) as ei:
        parse_package(d)
    assert "missing_profile" in str(ei.value.details)
    d = _demo_dict()
    d["isotp_profiles"]["ecu_a_normal"]["padding"]["byte"] = 0x100
    with pytest.raises(ValidationFailed) as ei:
        parse_package(d)
    assert any("padding.byte" in e["loc"] for e in ei.value.details)
    d = _demo_dict()
    d["tests"][0]["steps"][0] = {"send": {"payload": "22"}, "wait": 10}
    with pytest.raises(ValidationFailed):
        parse_package(d)


def test_collisions_between_packages(tmp_path: Path):
    pm = PackageManager([DEMO_PACKAGES], tmp_path / "user", tmp_path / "state.json")
    pm.scan()
    other = _demo_dict()
    other["package"]["id"] = "other"
    other.pop("simulation")
    pm.add(copy.deepcopy(other))
    pm.set_active(["demo"])
    with pytest.raises(ConflictError) as ei:
        pm.activate("other")
    assert ei.value.details and any("ecu_a" in c for c in ei.value.details)
    assert pm.active == ["demo"]


def test_package_lifecycle(tmp_path: Path):
    pm = PackageManager([DEMO_PACKAGES], tmp_path / "user", tmp_path / "state.json")
    pm.scan()
    pm.load_state(None)
    assert "demo" in pm.active  # Beispielpakete sind initial aktiv
    pkg = {"package": {"id": "mini", "version": "2.0.0"}, "messages": [{"id": "m1", "payload": "3E 00"}]}
    pm.add(pkg, activate=True)
    assert (tmp_path / "user" / "mini.yaml").exists()
    assert "m1" in pm.merged.messages
    with pytest.raises(ConflictError):
        pm.add(pkg)
    pm2 = PackageManager([DEMO_PACKAGES], tmp_path / "user", tmp_path / "state.json")
    pm2.scan()
    pm2.load_state(None)
    assert pm2.active == ["demo", "mini"]
    pm2.delete("mini")
    assert "mini" not in pm2.entries
    with pytest.raises(ConflictError):
        pm2.delete("demo")


def test_invalid_file_reported(tmp_path: Path):
    d = tmp_path / "pk"
    d.mkdir()
    (d / "broken.yaml").write_text("package: {id: 'x y'}\n")
    pm = PackageManager([d], tmp_path / "u", tmp_path / "s.json")
    pm.scan()
    assert pm.invalid and "broken.yaml" in pm.invalid[0]["file"]


def test_no_vendor_specific_defaults():
    from udsbench.isotp.profile import IsoTpProfile

    p = IsoTpProfile(tx_id=1, rx_id=2)
    assert p.addressing == "normal" and p.padding.enabled and p.timeouts.n_bs == 1000
