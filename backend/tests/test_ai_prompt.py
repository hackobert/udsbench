"""KI-Prompt zur Paketerstellung, KI-Antwort prüfen/importieren, Korrektur-Prompt."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from udsbench.cli import main
from udsbench.config.ai_prompt import EXAMPLE, build_fix_prompt, build_prompt, extract_yaml
from udsbench.config.loader import load_structured, parse_package
from udsbench.config.schema import Package
from udsbench.server import create_app

from .conftest import make_config


def test_example_in_prompt_is_importable():
    pkg = parse_package(load_structured(EXAMPLE))
    assert pkg.package.id == "project_x_ecu1" and pkg.isotp_profiles["ecu1_physical"].extended_id


def test_prompt_covers_schema_and_rules():
    text = build_prompt(package_id="p1", notes="nur Diagnoseadresse 0x10")
    for must in (
        "## Regeln",
        "## Ausgabeformat",
        "Offene Punkte",
        "Selbstprüfung",
        "`package.id: p1`",
        "Diagnoseadresse 0x10",
        "tx_address_extension",
        "security_levels",
        "dlc_mode",
        "Keine geheimen Verfahren",
    ):
        assert must in text, must
    # jedes Feld der wichtigsten Objekte steht in der Feldreferenz
    defs = Package.model_json_schema(by_alias=True)["$defs"]
    for name in ("IsoTpProfile", "EcuDef", "DidDef", "SecurityLevelDef", "TestDef"):
        for field in defs[name]["properties"]:
            assert f"`{field}`" in text, (name, field)
    assert "SimEcuConfig" not in text  # Simulation nur auf Wunsch
    assert "SimEcuConfig" in build_prompt(with_simulation=True)
    assert len(build_prompt(include_json_schema=True)) > len(text) + 20000


def test_extract_yaml_from_ai_answer():
    answer = "Hier ist das Paket:\n```yaml\npackage: {id: a}\n```\n## Offene Punkte\n- x\n```bash\necho\n```"
    assert extract_yaml(answer).strip() == "package: {id: a}"
    assert load_structured(answer) == {"package": {"id": "a"}}


def test_fix_prompt_contains_errors_and_content():
    t = build_fix_prompt("package: {id: a}", [{"loc": "ecus.0.isotp", "msg": "x"}], "Paket ist ungültig")
    assert "`ecus.0.isotp`" in t and "package: {id: a}" in t


def test_ai_check_api(tmp_path: Path):
    app = create_app(make_config(tmp_path, active_packages=[]), tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/v1/config/ai-prompt?package_id=x1&sections=isotp,ecus,dids&tests=false").json()
        assert "`package.id: x1`" in r["prompt"] and r["sections"] == ["isotp", "ecus", "dids"]
        assert c.get("/api/v1/config/ai-prompt?format=text").text.startswith("# Auftrag")
        bad = "```yaml\npackage: {id: bad_pkg}\necus: [{id: e1, isotp: nope, colour: red}]\n```"
        r = c.post("/api/v1/config/ai-check", json={"content": bad}).json()
        assert (
            not r["ok"] and any("colour" in e["loc"] for e in r["errors"]) and "Korrektur" in r["fix_prompt"]
        )
        good = "Antwort der KI:\n```yaml\n" + EXAMPLE + "```\n## Offene Punkte\n- Bibliothek fehlt\n"
        r = c.post("/api/v1/config/ai-check", json={"content": good}).json()
        assert r["ok"] and not r["imported"] and r["package"]["counts"]["ecus"] == 1
        assert any("TODO_keygen_library" in t for t in r["todos"])
        assert "Bibliothek fehlt" in r["todos"]
        r = c.post("/api/v1/config/ai-check", json={"content": good, "do_import": True}).json()
        assert r["imported"] and r["package"]["active"]
        assert "project_x_ecu1" in c.get("/api/v1/packages").json()["active"]


def test_cli_ai_prompt_and_check(tmp_path: Path, capsys):
    out = tmp_path / "prompt.md"
    assert main(["ai-prompt", "--package-id", "z", "-o", str(out)]) == 0
    assert "`package.id: z`" in out.read_text(encoding="utf-8")
    ans = tmp_path / "answer.md"
    ans.write_text("```yaml\n" + EXAMPLE + "```", encoding="utf-8")
    assert main(["ai-check", str(ans), "-o", str(tmp_path / "p.yaml")]) == 0
    ans.write_text("```yaml\npackage: {id: 'a b'}\n```", encoding="utf-8")
    capsys.readouterr()
    assert main(["ai-check", str(ans)]) == 1
    assert "Korrektur" in capsys.readouterr().out


def test_failed_import_leaves_no_package(tmp_path: Path):
    app = create_app(make_config(tmp_path), tmp_path)  # Demo-Paket aktiv
    with TestClient(app) as c:
        clash = "```yaml\npackage: {id: clash_pkg}\nmessages: [{id: read_identifier, payload: '3E 00'}]\n```"
        r = c.post("/api/v1/config/ai-check", json={"content": clash, "do_import": True}).json()
        assert not r["ok"] and not r["imported"]
        assert all(isinstance(e, dict) and e["msg"] for e in r["errors"]) and "read_identifier" in str(
            r["errors"]
        )
        assert "clash_pkg" not in [p["id"] for p in c.get("/api/v1/packages").json()["packages"]]
        assert not (tmp_path / "data" / "packages" / "clash_pkg.yaml").exists()
