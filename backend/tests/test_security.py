"""Seed-to-Key-Provider (demo/script/native/python/plugin) und Security-Ablauf."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from udsbench.core.errors import ProviderError
from udsbench.plugins.registry import registry
from udsbench.security.providers import create_provider


def test_demo_provider_documented_vector(tmp_path: Path):
    p = create_provider("d", "demo", {"mask": "5A A5"}, tmp_path)
    # Seed 01 02 03 04, Level 1 (lv = 0x11):
    # x0 = 01^5A^11 = 4A → rotl1 94 → +0 = 94 ; x1 = 02^A5^11 = B6 → 6D → +1 = 6E
    # x2 = 03^5A^11 = 48 → 90 → +2 = 92 ; x3 = 04^A5^11 = B0 → 61 → +3 = 64
    assert p.compute_key(bytes.fromhex("01020304"), 1, p.merged(None)) == bytes.fromhex("946E9264")


def test_script_provider_stdio_and_file(tmp_path: Path):
    script = tmp_path / "keygen.py"
    script.write_text(
        "import sys\nseed = bytes.fromhex(sys.stdin.read().strip())\nprint(bytes(b ^ 0xFF for b in seed).hex())\n"
    )
    p = create_provider("s", "script", {"command": [sys.executable, str(script)]}, tmp_path)
    assert p.compute_key(b"\x00\x0f", 1, p.merged(None)) == b"\xff\xf0"
    fscript = tmp_path / "keyfile.py"
    fscript.write_text(
        "import sys\nd=open(sys.argv[1],'rb').read()\nopen(sys.argv[2],'wb').write(d[::-1]+bytes([int(sys.argv[3])]))\n"
    )
    p2 = create_provider(
        "f",
        "script",
        {"mode": "file", "command": [sys.executable, str(fscript), "{seed_file}", "{key_file}", "{level}"]},
        tmp_path,
    )
    assert p2.compute_key(b"\x01\x02", 3, p2.merged(None)) == b"\x02\x01\x03"
    bad = create_provider(
        "b", "script", {"command": [sys.executable, "-c", "import sys; sys.exit(3)"]}, tmp_path
    )
    with pytest.raises(ProviderError):
        bad.compute_key(b"\x00", 1, bad.merged(None))


@pytest.mark.skipif(shutil.which("cc") is None and shutil.which("gcc") is None, reason="kein C-Compiler")
def test_native_provider_with_config_described_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    src = tmp_path / "toy.c"
    src.write_text(
        "#include <stdint.h>\n#include <string.h>\n"
        "static uint8_t g_x = 0;\n"
        "int Init(const char* v){ g_x = (uint8_t)strlen(v); return 0; }\n"
        "int Gen(const uint8_t* seed, uint32_t n, uint32_t level, const char* variant, uint8_t* key, uint32_t cap, uint32_t* klen){\n"
        "  if (n > cap) return 1; for (uint32_t i=0;i<n;i++) key[i] = seed[i] ^ (uint8_t)level ^ g_x ^ (uint8_t)variant[0];\n"
        "  *klen = n; return 0; }\n"
    )
    ext = ".dll" if sys.platform == "win32" else (".dylib" if sys.platform == "darwin" else ".so")
    lib = tmp_path / f"libtoy{ext}"
    cc = shutil.which("cc") or shutil.which("gcc")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(lib), str(src)], check=True)
    monkeypatch.setenv("TOY_VARIANT", "A")
    params = {
        "library": lib.name,
        "function": "Gen",
        "key_buffer_size": 16,
        "args": [
            "seed_ptr",
            {"seed_len": "uint32"},
            {"level": "uint32"},
            {"const_str": "${ENV:TOY_VARIANT}"},
            "key_ptr",
            {"key_buffer_size": "uint32"},
            "key_len_ptr",
        ],
        "return": {"type": "int", "success": 0},
        "init": [{"function": "Init", "args": [{"const_str": "abc"}], "success": 0}],
    }
    p = create_provider("n", "native", params, tmp_path)
    key = p.compute_key(b"\x10\x20", 1, p.merged(None))
    assert key == bytes([0x10 ^ 1 ^ 3 ^ 0x41, 0x20 ^ 1 ^ 3 ^ 0x41])
    with pytest.raises(ProviderError):
        create_provider("x", "native", {"library": "missing.so", "function": "f"}, tmp_path).compute_key(
            b"\x00", 1, {"library": "missing.so", "function": "f"}
        )


def test_python_and_plugin_provider(tmp_path: Path):
    f = tmp_path / "prov.py"
    f.write_text("def compute_key(seed, level, params):\n    return bytes(b + level for b in seed)\n")
    p = create_provider("py", "python", {"file": "prov.py"}, tmp_path)
    assert p.compute_key(b"\x01", 2, p.merged(None)) == b"\x03"
    registry.add_key_function("toy_plugin", lambda s, lvl, prm: s[::-1])
    pp = create_provider("pl", "plugin", {"function": "toy_plugin"}, tmp_path)
    assert pp.compute_key(b"\x01\x02", 1, pp.merged(None)) == b"\x02\x01"


async def test_unlock_flow_and_audit_log(platform):
    from udsbench.logs.setup import get_buffer

    res = await platform.security.unlock("ecu_a", 0x01)
    assert res["unlocked"] and platform.diag.get("ecu_a").unlocked == {0x01}
    audit = get_buffer().query(channel="audit")
    assert any("erfolgreich" in a["msg"] for a in audit)
    # keine Seeds/Keys im Klartext im Kommunikations-Log
    comm = get_buffer().query(channel="comm")
    assert all("27 02 " not in c["msg"] or "***" in c["msg"] for c in comm)


async def test_nrc_suite_passes_against_testdouble(platform):
    tests = platform.security.nrc_cases("ecu_a", 0x01)
    ids = [t.id.split(".")[1] for t in tests]
    for required in (
        "invalid_key",
        "wrong_length",
        "unsupported_subfunction",
        "key_without_seed",
        "exceed_attempts",
        "time_delay",
        "conditions_not_correct",
        "service_not_supported",
        "out_of_range",
        "positive_reference",
    ):
        assert required in ids
    run = platform.runner.start_adhoc("security_nrc", "ecu_a", "NRC", tests, ecu="ecu_a")
    await platform.runner.wait(run.id, 60)
    bad = [(t.name, t.message) for t in run.tests if t.status != "passed"]
    assert run.status == "passed", bad
