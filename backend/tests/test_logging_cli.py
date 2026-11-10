"""Logging (Kanäle, JSONL, Maskierung, Korrelation), Plugin-Loader und CLI."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from udsbench.cli import main
from udsbench.core.context import correlated
from udsbench.logs.setup import get_buffer, mask_uds, setup_logging
from udsbench.plugins.registry import PluginRegistry

from .conftest import DEMO_PACKAGES


def test_jsonl_channels_masking_and_correlation(tmp_path: Path):
    setup_logging("TRACE", tmp_path, console=False)
    with correlated("run_abc"):
        logging.getLogger("udsbench.audit.x").info("Unlock seed=AA BB CC", extra={"key": "0102", "ecu": "e1"})
        logging.getLogger("udsbench.comm.uds").log(5, "TX frame")
        logging.getLogger("udsbench.test.y").warning("Schritt fehlgeschlagen")
    for h in logging.getLogger("udsbench").handlers:
        h.flush()
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["cid"] == "run_abc" and audit[-1]["key"] == "***" and "AA BB" not in audit[-1]["msg"]
    assert audit[-1]["ecu"] == "e1" and audit[-1]["channel"] == "audit"
    comm = [json.loads(line) for line in (tmp_path / "comm.jsonl").read_text().splitlines()]
    assert comm[-1]["level"] == "TRACE"
    assert (tmp_path / "test.jsonl").exists() and (tmp_path / "app.jsonl").exists()
    assert get_buffer().query(cid="run_abc", channel="test")
    assert mask_uds(bytes.fromhex("6701AABBCCDD")) == "67 01 ***"
    assert mask_uds(bytes.fromhex("22F190")) == "22 F1 90"


def test_plugin_loader(tmp_path: Path):
    (tmp_path / "good.py").write_text(
        "def register(r):\n    r.add_decoder('d1', lambda data, spec: data[::-1])\n"
    )
    (tmp_path / "bad.py").write_text("raise RuntimeError('kaputt')\n")
    (tmp_path / "ignored.example.py").write_text("raise RuntimeError('darf nicht geladen werden')\n")
    reg = PluginRegistry()
    reg.load_dir(tmp_path)
    s = reg.summary()
    assert s["decoders"] == ["d1"]
    assert {f["file"]: f["ok"] for f in s["files"]} == {"bad.py": False, "good.py": True}


def test_cli_validate_and_schema(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    assert main(["validate", str(DEMO_PACKAGES / "demo.example.yaml")]) == 0
    bad = tmp_path / "bad.yaml"
    bad.write_text("package: {id: x}\necus: [{id: e, isotp: nope}]\n")
    assert main(["validate", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "FEHLER" in out and "nope" in out
    assert main(["schema", "package"]) == 0
    assert '"title": "Package"' in capsys.readouterr().out
