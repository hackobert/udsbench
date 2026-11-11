"""End-to-End über die API: kompletter Testlauf ohne UI (Verbinden → Paket → Suite → Report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from udsbench.server import create_app

from .conftest import make_config, unique_bus

pytestmark = pytest.mark.integration
TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path: Path):
    cfg = make_config(tmp_path, server={"token": TOKEN}, active_packages=[])
    app = create_app(cfg, tmp_path)
    with TestClient(app) as c:
        yield c


def test_auth_and_error_format(client: TestClient):
    assert client.get("/api/health").json()["auth_required"] is True
    r = client.get("/api/v1/info")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/info", headers={"X-API-Token": TOKEN}).status_code == 200
    r = client.post("/api/v1/uds/request", json={"ecu": "nope", "payload": "3E00"}, headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post("/api/v1/connection", json={"backend": "nope"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["details"]


def test_full_automation_flow(client: TestClient):
    # 1. Paket aktivieren
    assert client.post("/api/v1/packages/demo/activate", headers=H).json()["active"] == ["demo"]
    # 2. Verbinden (virtueller Bus + Testdouble)
    r = client.post(
        "/api/v1/connection",
        json={"name": "default", "backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
        headers=H,
    )
    assert r.status_code == 200 and sorted(r.json()["simulation"]) == ["ecu_a", "ecu_b", "ecu_c"]
    # 3. Suite ausführen (asynchron) und Status abfragen
    run = client.post("/api/v1/testsuites/full/run", json={}, headers=H).json()
    run_id = run["run_id"]
    import time

    for _ in range(200):
        st = client.get(f"/api/v1/runs/{run_id}", headers=H).json()
        if st["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert st["status"] == "passed", st["summary"]
    # 4. Reports abholen
    junit = client.get(f"/api/v1/runs/{run_id}/report?format=junit", headers=H)
    assert junit.status_code == 200 and junit.text.startswith("<?xml")
    rep = json.loads(client.get(f"/api/v1/runs/{run_id}/report?format=json", headers=H).text)
    assert rep["summary"]["passed"] == 12 and rep["environment"]["packages"]
    # Korrelation: Test-Logs tragen die Run-ID
    logs = client.get(f"/api/v1/logs?channel=test&cid={run_id}", headers=H).json()["items"]
    assert logs and all(entry["cid"] == run_id for entry in logs)


def test_uds_endpoints(client: TestClient):
    client.post("/api/v1/packages/demo/activate", headers=H)
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
        headers=H,
    )
    r = client.post("/api/v1/uds/request", json={"ecu": "ecu_a", "payload": "22 F1 00"}, headers=H).json()
    assert r["positive"] and r["decoded"]["fields"]["records"][0]["value"] == "DEMO-ECU-A-000001"
    r = client.post("/api/v1/uds/request", json={"ecu": "ecu_a", "payload": "10"}, headers=H)
    assert r.status_code == 422  # Validierung vor dem Senden
    r = client.post(
        "/api/v1/uds/request", json={"ecu": "ecu_a", "payload": "10", "validate": "off"}, headers=H
    ).json()
    assert r["nrc"] == 0x13
    pv = client.post("/api/v1/uds/preview", json={"ecu": "ecu_b", "payload": "22 F1 00"}, headers=H).json()
    roles = [b["role"] for b in pv["frames"][0]["bytes"]]
    assert roles[:2] == ["ae", "pci"] and roles[-1] == "pad" and pv["frames"][0]["bytes"][-1]["value"] == "FF"
    pv = client.post(
        "/api/v1/uds/preview",
        json={
            "profile": {"tx_id": 1, "rx_id": 2, "padding": {"enabled": False}, "dlc_mode": "minimal"},
            "payload": "3E 00",
        },
        headers=H,
    ).json()
    assert pv["frames"][0]["dlc"] == 3
    assert len(client.get("/api/v1/uds/services", headers=H).json()["services"]) >= 26
    assert (
        client.post("/api/v1/dids/read", json={"ecu": "ecu_a", "dids": ["supply_voltage"]}, headers=H).json()[
            "vars"
        ]["values"]["supply_voltage"]
        == 12.6
    )
    r = client.post(
        "/api/v1/dtcs/read", json={"ecu": "ecu_a", "subfunction": 2, "mask": 255}, headers=H
    ).json()
    assert len(r["result"]["decoded"]["fields"]["dtcs"]) == 3
    r = client.post("/api/v1/security/unlock", json={"ecu": "ecu_a", "level": 1}, headers=H).json()
    assert r["unlocked"]
    r = client.post(
        "/api/v1/dids/write", json={"ecu": "ecu_a", "did": "user_setting", "value": 42}, headers=H
    ).json()
    assert r["step"]["status"] == "passed"
    r = client.post(
        "/api/v1/routines/control", json={"ecu": "ecu_a", "routine": "demo_self_test"}, headers=H
    ).json()
    assert r["result"]["pending_count"] == 2
    r = client.post(
        "/api/v1/transfer",
        json={"ecu": "ecu_a", "direction": "upload", "address": "0x1000", "size": 16},
        headers=H,
    ).json()
    assert r["step"]["status"] == "passed", r
    seed = client.post("/api/v1/security/seed", json={"ecu": "ecu_b", "level": 1}, headers=H).json()
    assert seed["result"]["nrc"] == 0x7F  # DefaultSession
    r = client.post(
        "/api/v1/security/compute-key", json={"seed": "01020304", "provider": "demo_toy"}, headers=H
    ).json()
    assert r["key"] == "94 6E 92 64"


def test_workspace_crud_and_sequences(client: TestClient):
    client.post("/api/v1/packages/demo/activate", headers=H)
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
        headers=H,
    )
    r = client.post(
        "/api/v1/messages",
        json={"id": "m_x", "payload": "22 ${u16(d)}", "vars": {"d": 0xF101}, "ecu": "ecu_a"},
        headers=H,
    )
    assert r.status_code == 200
    assert (
        client.post(
            "/api/v1/messages", json={"id": "read_identifier", "payload": "3E00"}, headers=H
        ).status_code
        == 409
    )
    assert client.post("/api/v1/messages/m_x/preview", json={}, headers=H).json()["payload"] == "22 F1 01"
    assert client.post("/api/v1/messages/m_x/send", headers=H).json()["step"]["status"] == "passed"
    seq = {
        "id": "s_x",
        "ecu": "ecu_a",
        "steps": [{"send": {"message": "m_x"}, "save": {"v": "data[2:]"}}, {"assert": "len(v) == 8"}],
    }
    assert client.post("/api/v1/sequences", json=seq, headers=H).status_code == 200
    rep = client.post("/api/v1/sequences/s_x/run", json={"wait": True}, headers=H).json()
    assert rep["status"] == "passed"
    bad = client.post("/api/v1/tests", json={"id": "t_bad", "steps": [{"nonsense": 1}]}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["details"]
    assert client.delete("/api/v1/messages/read_identifier", headers=H).status_code == 409
    assert client.delete("/api/v1/sequences/s_x", headers=H).status_code == 200
    pk = client.get("/api/v1/packages", headers=H).json()
    assert "workspace" in pk["active"]


def test_nrc_suite_api(client: TestClient):
    client.post("/api/v1/packages/demo/activate", headers=H)
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
        headers=H,
    )
    rep = client.post(
        "/api/v1/security/nrc-suite/run", json={"ecu": "ecu_a", "level": 1, "wait": True}, headers=H
    ).json()
    assert rep["status"] == "passed", [
        (t["name"], t["message"]) for t in rep["tests"] if t["status"] != "passed"
    ]


def test_package_import_export_and_config(client: TestClient):
    text = "package: {id: imp1, version: '1.2.3'}\nmessages: [{id: m_imp, payload: '3E 00'}]\n"
    r = client.post("/api/v1/config/import", json={"content": text, "activate": True}, headers=H)
    assert r.status_code == 200 and r.json()["package"]["version"] == "1.2.3"
    exp = client.get("/api/v1/config/export?package=imp1&format=json", headers=H)
    assert json.loads(exp.text)["package"]["id"] == "imp1"
    bad = client.post("/api/v1/config/validate", json={"content": "package: {id: 'a b'}"}, headers=H)
    assert bad.status_code == 422
    cfg = client.get("/api/v1/config", headers=H).json()
    assert cfg["server"]["token"] == "***"
    r = client.put("/api/v1/config", json={"log_level": "DEBUG"}, headers=H).json()
    assert r["logging"]["level"] == "DEBUG"
    assert client.get("/api/v1/config/schema?kind=package", headers=H).json()["title"] == "Package"


def test_websockets(client: TestClient):
    client.post("/api/v1/packages/demo/activate", headers=H)
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
        headers=H,
    )
    with client.websocket_connect(f"/ws/events?token={TOKEN}&topics=uds,hello") as ev:
        assert json.loads(ev.receive_text())["topic"] == "hello"
        with client.websocket_connect(f"/ws/trace?token={TOKEN}") as ws:
            ws.send_text(json.dumps({"action": "filter", "filter": {"ids": "0x700"}}))
            assert json.loads(ws.receive_text())["type"] == "ack"
            client.post("/api/v1/uds/request", json={"ecu": "ecu_a", "payload": "3E 00"}, headers=H)
            batch = json.loads(ws.receive_text())
            assert batch["type"] == "batch" and all(f["id"] == 0x700 for f in batch["frames"])
        evt = json.loads(ev.receive_text())
        assert evt["topic"] == "uds" and evt["result"]["positive"]
    import contextlib

    from starlette.websockets import WebSocketDisconnect

    with contextlib.suppress(WebSocketDisconnect), client.websocket_connect("/ws/trace") as ws:
        ws.receive_text()
        raise AssertionError("WS ohne Token muss abgewiesen werden")


def test_openapi_covers_required_routes(client: TestClient):
    paths = set(client.get("/openapi.json").json()["paths"])
    required = [
        "/api/v1/interfaces",
        "/api/v1/connection",
        "/api/v1/config",
        "/api/v1/config/import",
        "/api/v1/config/export",
        "/api/v1/packages",
        "/api/v1/packages/{pid}/activate",
        "/api/v1/uds/services",
        "/api/v1/uds/request",
        "/api/v1/ecus",
        "/api/v1/isotp/profiles",
        "/api/v1/catalogs/dids",
        "/api/v1/catalogs/dtcs",
        "/api/v1/catalogs/routines",
        "/api/v1/messages",
        "/api/v1/messages/{mid}/send",
        "/api/v1/sequences",
        "/api/v1/sequences/{sid}/run",
        "/api/v1/security/seed",
        "/api/v1/security/key",
        "/api/v1/security/unlock",
        "/api/v1/tests",
        "/api/v1/tests/{tid}/run",
        "/api/v1/testsuites/{sid}/run",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/report",
        "/api/v1/recordings",
        "/api/v1/recordings/{rid}/replay",
        "/api/v1/logs",
        "/api/v1/logs/stream",
    ]
    missing = [r for r in required if r not in paths]
    assert not missing, missing


def test_connection_replace(client: TestClient):
    """--demo verbindet 'default' virtuell; Umstellen auf Hardware muss ohne Trennen gehen."""
    bus = unique_bus()
    body = {"name": "default", "backend": "virtual", "options": {"bus": bus}}
    assert client.post("/api/v1/connection", json=body, headers=H).status_code == 200
    r = client.post("/api/v1/connection", json=body, headers=H)
    assert r.status_code == 409 and "trennen" in r.json()["error"]["message"]
    # Umstellen auf ein Interface, das sich nicht öffnen lässt: Fehler, alte Verbindung bleibt
    bad = {"name": "default", "backend": "python-can", "options": {"interface": "does-not-exist"}}
    r = client.post("/api/v1/connection?replace=true", json=bad, headers=H)
    assert r.status_code >= 400 and "vorherige Verbindung bleibt aktiv" in r.json()["error"]["message"]
    ch = client.get("/api/v1/connection", headers=H).json()["channels"]
    assert [(c["name"], c["backend"], c["connected"]) for c in ch] == [("default", "virtual", True)]
    # Umstellen auf einen anderen virtuellen Bus klappt
    other = {"name": "default", "backend": "virtual", "options": {"bus": unique_bus()}}
    assert client.post("/api/v1/connection?replace=true", json=other, headers=H).status_code == 200
