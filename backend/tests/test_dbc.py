"""DBC-Bereich: Upload, Kanalzuordnung, Trace-Dekodierung, Live-Werte, Kodieren/Senden."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from udsbench.server import create_app

from .conftest import make_config, unique_bus

pytestmark = pytest.mark.integration
SAMPLE = (Path(__file__).parent / "data" / "sample.dbc").read_text()


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(make_config(tmp_path), tmp_path)) as c:
        yield c


def test_upload_assign_describe_delete(client: TestClient):
    r = client.post("/api/v1/dbc", json={"filename": "Sample Car.dbc", "content": SAMPLE})
    assert r.status_code == 200, r.text
    f = r.json()["file"]
    assert f["id"] == "Sample_Car" and f["messages"] == 3 and f["signals"] == 7
    assert (
        client.post("/api/v1/dbc", json={"filename": "Sample Car.dbc", "content": SAMPLE}).status_code == 422
    )
    bad = client.post("/api/v1/dbc", json={"filename": "x.dbc", "content": "BO_ kaputt"})
    assert bad.status_code == 422
    d = client.get("/api/v1/dbc/files/Sample_Car").json()
    eng = next(m for m in d["messages"] if m["name"] == "EngineData")
    sig = {s["name"]: s for s in eng["signals"]}
    assert sig["EngineSpeed"]["unit"] == "rpm" and sig["EngineSpeed"]["comment"] == "Motordrehzahl"
    assert sig["Mode"]["choices"] == {"0": "off", "1": "standby", "2": "active", "3": "fault"}
    j = next(m for m in d["messages"] if m["name"] == "J1939Msg")
    assert j["extended"] and j["id"] == 0x18FEF1FE
    # Zuordnung pro Kanal
    assert client.put("/api/v1/dbc/channels/default", json={"files": ["Sample_Car"]}).status_code == 200
    assert client.put("/api/v1/dbc/channels/can2", json={"files": ["nope"]}).status_code == 404
    ov = client.get("/api/v1/dbc").json()
    assert ov["assignments"] == {"default": ["Sample_Car"]}
    assert ov["files"][0]["channels"] == ["default"]
    assert {"name": "default", "connected": False} in ov["channels"]
    msgs = client.get("/api/v1/dbc/channels/default/messages").json()
    assert {m["name"] for m in msgs} == {"EngineData", "J1939Msg", "Status"}
    assert client.get("/api/v1/dbc/channels/can2/messages").json() == []
    # löschen entfernt auch die Zuordnung
    assert client.delete("/api/v1/dbc/files/Sample_Car").status_code == 200
    assert client.get("/api/v1/dbc").json()["assignments"] == {}


def test_decode_in_trace_and_live_per_channel(client: TestClient):
    client.post("/api/v1/dbc", json={"filename": "car.dbc", "content": SAMPLE, "channels": ["default"]})
    bus = unique_bus()
    client.post("/api/v1/connection", json={"name": "default", "backend": "virtual", "options": {"bus": bus}})
    client.post("/api/v1/connection", json={"name": "other", "backend": "virtual", "options": {"bus": bus}})
    # Kodieren + Senden auf "other" → wird auf "default" empfangen und dort dekodiert
    r = client.post(
        "/api/v1/dbc/encode",
        json={
            "channel": "default",
            "message": "EngineData",
            "signals": {"EngineSpeed": 1500, "CoolantTemp": 90, "Mode": "active"},
        },
    ).json()
    assert r["data"] == "70 17 82 02 00 00 00 00" and r["sent"] is False
    other_send = client.post("/api/v1/can/send", json={"channel": "other", "id": "0x100", "data": r["data"]})
    assert other_send.status_code == 200
    time.sleep(0.05)
    live = client.get("/api/v1/dbc/live?channel=default").json()["messages"]
    assert len(live) == 1 and live[0]["message"] == "EngineData"
    assert live[0]["signals"] == {"EngineSpeed": 1500.0, "CoolantTemp": 90, "Mode": "active"}
    assert live[0]["units"] == {"EngineSpeed": "rpm", "CoolantTemp": "degC"}
    # Kanal "other" hat keine DBC → keine Dekodierung
    assert client.get("/api/v1/dbc/live?channel=other").json()["messages"] == []
    frames = client.get("/api/v1/trace?view=frames&limit=50").json()
    items = frames["items"] if isinstance(frames, dict) else frames
    rx = [f for f in items if f.get("channel") == "default" and f.get("dbc")]
    assert rx and rx[-1]["text"].startswith("EngineData: EngineSpeed=1500 rpm")
    # Multiplexer und extended ID
    client.post("/api/v1/can/send", json={"channel": "other", "id": "0x200", "data": "02 FF"})
    client.post(
        "/api/v1/can/send", json={"channel": "other", "id": "0x18FEF1FE", "data": "2A", "extended": True}
    )
    time.sleep(0.05)
    live = {m["message"]: m for m in client.get("/api/v1/dbc/live?channel=default").json()["messages"]}
    assert live["Status"]["signals"] == {"Mux": 2, "B": -1}
    assert live["J1939Msg"]["signals"] == {"Value": 42} and live["J1939Msg"]["extended"]
    # Senden über die DBC
    s = client.post(
        "/api/v1/dbc/encode",
        json={"channel": "default", "message": "Status", "signals": {"Mux": 1, "A": 7}, "send": True},
    )
    assert s.status_code == 200 and s.json()["sent"] and s.json()["data"] == "01 07"
    bad = client.post(
        "/api/v1/dbc/encode", json={"channel": "default", "message": "EngineData", "signals": {"Nope": 1}}
    )
    assert bad.status_code == 422
    assert (
        client.post("/api/v1/dbc/encode", json={"channel": "default", "message": "Unknown"}).status_code
        == 404
    )
    assert client.delete("/api/v1/dbc/live?channel=default").status_code == 200


def test_persisted_across_restart(tmp_path: Path):
    with TestClient(create_app(make_config(tmp_path), tmp_path)) as c:
        c.post("/api/v1/dbc", json={"filename": "car.dbc", "content": SAMPLE, "channels": ["can1"]})
    with TestClient(create_app(make_config(tmp_path), tmp_path)) as c:
        ov = c.get("/api/v1/dbc").json()
        assert ov["assignments"] == {"can1": ["car"]} and ov["files"][0]["messages"] == 3


def test_conflicts_reported(client: TestClient):
    client.post("/api/v1/dbc", json={"filename": "a.dbc", "content": SAMPLE})
    client.post("/api/v1/dbc", json={"filename": "b.dbc", "content": SAMPLE})
    r = client.put("/api/v1/dbc/channels/default", json={"files": ["a", "b"]}).json()
    assert len(r["conflicts"]) == 3 and "verdeckt" in r["conflicts"][0]
