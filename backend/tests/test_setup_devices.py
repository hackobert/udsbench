"""Einrichtungsassistent: eigene Geräte anlegen/ändern/löschen, Demo ausblenden, Verbindung speichern."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from udsbench.server import create_app

from .conftest import make_config, unique_bus

pytestmark = pytest.mark.integration


@pytest.fixture
def client(tmp_path: Path):
    cfg = make_config(tmp_path)
    with TestClient(create_app(cfg, tmp_path)) as c:
        yield c


def device(**profile: object) -> dict[str, object]:
    return {
        "id": "my_ecu",
        "name": "Mein Steuergerät",
        "isotp": {"tx_id": 0x7E0, "rx_id": 0x7E8, "functional_id": 0x7DF, **profile},
    }


def test_demo_devices_listed_read_only(client: TestClient):
    devs = {d["id"]: d for d in client.get("/api/v1/devices").json()}
    assert devs["ecu_a"]["demo"] and not devs["ecu_a"]["editable"]
    r = client.delete("/api/v1/devices/ecu_a")
    assert r.status_code == 409 and "Demo" in r.json()["error"]["message"]


def test_hide_and_show_demo(client: TestClient):
    st = client.get("/api/v1/setup").json()
    assert st["demo"] == {"available": True, "active": True, "packages": ["demo"]}
    assert st["completed"] is False and st["devices"]["demo"] == 3
    assert client.put("/api/v1/setup/demo", json={"enabled": False}).status_code == 200
    assert client.get("/api/v1/devices").json() == []
    assert client.get("/api/v1/setup").json()["demo"]["active"] is False
    client.put("/api/v1/setup/demo", json={"enabled": True})
    assert len(client.get("/api/v1/devices").json()) == 3


def test_device_crud(client: TestClient):
    client.put("/api/v1/setup/demo", json={"enabled": False})
    r = client.post("/api/v1/devices", json=device(padding={"enabled": True, "byte": 0x55}))
    assert r.status_code == 200, r.text
    d = r.json()["device"]
    assert d["editable"] and d["package"] == "workspace" and r.json()["warnings"] == []
    assert d["profile"]["tx_id"] == 0x7E0 and d["profile"]["padding"]["byte"] == 0x55
    # erscheint als ECU und ist über UDS ansprechbar
    assert [e["id"] for e in client.get("/api/v1/ecus").json()] == ["my_ecu"]
    # doppelt anlegen → Konflikt
    assert client.post("/api/v1/devices", json=device()).status_code == 409
    # ändern
    upd = device(tx_id=0x7E1, rx_id=0x7E9)
    upd["name"] = "Umbenannt"
    assert client.put("/api/v1/devices/my_ecu", json=upd).status_code == 200
    d = client.get("/api/v1/devices/my_ecu").json()
    assert d["name"] == "Umbenannt" and d["profile"]["rx_id"] == 0x7E9
    # löschen
    assert client.delete("/api/v1/devices/my_ecu").status_code == 200
    assert client.get("/api/v1/devices").json() == []


def test_device_validation_and_id_warning(client: TestClient):
    r = client.post("/api/v1/devices", json=device(addressing="extended"))
    assert r.status_code == 422  # extended ohne Adressbyte
    r = client.post("/api/v1/devices", json=device(tx_id=0x701, rx_id=0x708))  # rx wie Demo-ECU A
    assert r.status_code == 200 and "ecu_a" in r.json()["warnings"][0]


def test_device_talks_to_simulated_ecu(client: TestClient):
    """Gerät mit den IDs der Demo-ECU A anlegen → Kommunikation über den virtuellen Bus klappt."""
    bus = unique_bus()
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": bus}, "simulate": True},
    )
    r = client.post("/api/v1/devices", json=device(tx_id=0x700, rx_id=0x708, functional_id=None))
    assert r.status_code == 200
    res = client.post("/api/v1/uds/request", json={"ecu": "my_ecu", "payload": "3E 00"}).json()
    assert res["positive"], res


def test_saved_connection_used_on_next_start(tmp_path: Path):
    cfg = make_config(tmp_path)
    bus = unique_bus()
    with TestClient(create_app(cfg, tmp_path)) as c:
        spec = {"name": "default", "backend": "virtual", "options": {"bus": bus}}
        assert c.put("/api/v1/setup/connections", json=[spec]).status_code == 200
        c.put("/api/v1/setup/completed", json={"completed": True})
        assert c.get("/api/v1/connection").json()["channels"] == []
    with TestClient(create_app(make_config(tmp_path), tmp_path)) as c:
        ch = c.get("/api/v1/connection").json()["channels"]
        assert [(x["name"], x["connected"]) for x in ch] == [("default", True)]
        assert c.get("/api/v1/setup").json()["completed"] is True


def test_bus_activity(client: TestClient):
    assert client.get("/api/v1/setup/bus-activity?seconds=0.1").status_code >= 400  # nicht verbunden
    client.post(
        "/api/v1/connection",
        json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
    )
    import threading

    t = threading.Timer(
        0.1, lambda: client.post("/api/v1/uds/request", json={"ecu": "ecu_a", "payload": "3E00"})
    )
    t.start()
    r = client.get("/api/v1/setup/bus-activity?seconds=0.6").json()
    t.join()
    assert r["frames"] >= 1 and any(e["id"] == 0x708 for e in r["ids"])
