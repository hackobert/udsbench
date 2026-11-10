"""Ereignis-Historie, Statistik/Timechart, manuelle Reports, Run-Export, Dashboards & Aktionen."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from udsbench.core.history import HistoryStore, bucketize
from udsbench.reports.service import ReportSpec, parse_time
from udsbench.server import create_app

from .conftest import make_config, unique_bus

pytestmark = pytest.mark.integration


def test_parse_time():
    now = 1_000_000.0
    assert parse_time("-15m", now) == now - 900
    assert parse_time("now", now) == now
    assert parse_time(123.5, now) == 123.5
    assert parse_time("2026-01-01T00:00:00+00:00") == 1767225600.0


def test_bucketize_and_history_persistence(tmp_path: Path):
    h = HistoryStore(tmp_path)
    t0 = time.time() - 10
    for i in range(10):
        h.add(
            {
                "ts": t0 + i,
                "topic": "uds",
                "type": "positive" if i % 3 else "negative",
                "elapsed_ms": float(i),
            }
        )
    h.close()
    series = bucketize(h.query(t0 - 1, t0 + 20), t0, t0 + 10, 5, "type")
    assert series["total"] == 10 and series["groups"] == {"positive": 6, "negative": 4}
    assert [b["total"] for b in series["buckets"]] == [5, 5]
    assert series["buckets"][0]["latency_max_ms"] == 4.0
    # neue Instanz (z. B. nach Neustart) liest frühere Zeiträume aus den Tagesdateien
    h2 = HistoryStore(tmp_path)
    assert len(h2.query(t0 - 1, t0 + 20)) == 10


async def test_history_records_uds_and_session(platform):
    rt = platform.diag.get("ecu_a")
    await rt.request(bytes.fromhex("1003"))
    await rt.request(bytes.fromhex("1004"))
    await rt.request(bytes.fromhex("22F100"))
    ev = platform.history.query(time.time() - 10)
    uds = [e for e in ev if e["topic"] == "uds"]
    assert [e["type"] for e in uds] == ["positive", "negative", "positive"]
    assert uds[1]["nrc"] == 0x12 and uds[0]["service"] == "DiagnosticSessionControl"
    assert any(e["topic"] == "session" for e in ev)


async def test_manual_report_with_traces(platform):
    t_start = time.time() - 0.1
    run = platform.runner.start_suite("smoke")
    await platform.runner.wait(run.id, 30)
    await platform.diag.get("ecu_a").request(bytes.fromhex("1004"))
    rep = platform.reports.create(
        ReportSpec.model_validate(
            {
                "title": "Prüfstand Lauf 1",
                "from": t_start,
                "to": "now",
                "notes": "Notiz",
                "trace_formats": ["asc", "candump"],
            }
        )
    )
    full = platform.reports.get(rep["id"])
    assert full["stats"]["uds_requests"] >= 5 and full["stats"]["uds_totals"]["negative"] >= 1
    assert full["stats"]["frames"] > 0 and full["runs"][0]["run_id"] == run.id
    names = {a["name"] for a in rep["attachments"]}
    assert {
        "trace.asc",
        "trace.candump",
        "uds_messages.csv",
        "events.jsonl",
        f"run_{run.id}.junit.xml",
    } <= names
    html = platform.reports.html(rep["id"])
    assert "Prüfstand Lauf 1" in html and "<svg" in html and "Notiz" in html
    z = zipfile.ZipFile(io.BytesIO(platform.reports.zip(rep["id"])))
    assert f"{rep['id']}/trace.asc" in z.namelist() and f"{rep['id']}/report.html" in z.namelist()
    assert platform.reports.list_items()[0]["id"] == rep["id"]
    platform.reports.delete(rep["id"])
    assert platform.reports.list_items() == []


async def test_run_bundle_contains_trace_and_logs(platform):
    run = platform.runner.start_test("read_identification")
    await platform.runner.wait(run.id, 10)
    z = zipfile.ZipFile(io.BytesIO(platform.reports.run_bundle(run.id)))
    names = z.namelist()
    for n in (
        "report.json",
        "report.junit.xml",
        "report.html",
        "trace.asc",
        "trace.csv",
        "trace.jsonl",
        "logs.jsonl",
    ):
        assert f"{run.id}/{n}" in names
    assert (
        "62 F1 00" in z.read(f"{run.id}/trace.asc").decode() or "62" in z.read(f"{run.id}/trace.csv").decode()
    )
    logs = [json.loads(x) for x in z.read(f"{run.id}/logs.jsonl").decode().splitlines() if x]
    assert logs and all(entry["cid"] == run.id for entry in logs)


TOKEN = "tkn"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(make_config(tmp_path, server={"token": TOKEN}), tmp_path)
    with TestClient(app) as c:
        c.post(
            "/api/v1/connection",
            json={"backend": "virtual", "options": {"bus": unique_bus()}, "simulate": True},
            headers=H,
        )
        yield c


def test_stats_and_events_api(client: TestClient):
    for payload in ("22 F1 00", "10 04", "3E 00"):
        client.post("/api/v1/uds/request", json={"ecu": "ecu_a", "payload": payload}, headers=H)
    client.post("/api/v1/events/marker", json={"text": "Zündung an"}, headers=H)
    ts = client.get("/api/v1/stats/timeseries?metric=uds&group_by=type&from=-1m", headers=H).json()
    assert ts["groups"] == {"positive": 2, "negative": 1}
    fr = client.get(
        "/api/v1/stats/timeseries?metric=frames&group_by=type&from=-1m&bucket_s=10", headers=H
    ).json()
    assert fr["total"] > 0 and fr["bucket_s"] == 10 and "FC" in fr["groups"]
    sv = client.get("/api/v1/stats/timeseries?metric=uds&group_by=service&from=-1m", headers=H).json()
    assert "ReadDataByIdentifier" in sv["groups"]
    s = client.get("/api/v1/stats/summary?from=-1m", headers=H).json()
    assert s["uds_requests"] == 3 and s["nrc_counts"] and s["latency"]["count"] == 3
    ev = client.get("/api/v1/events?from=-1m&topics=marker", headers=H).json()["items"]
    assert ev[-1]["text"] == "Zündung an"


def test_reports_and_run_export_api(client: TestClient):
    run = client.post("/api/v1/testsuites/smoke/run", json={"wait": True}, headers=H).json()
    assert client.get(f"/api/v1/runs/{run['run_id']}/report?format=html", headers=H).text.startswith(
        "<!doctype html>"
    )
    z = client.get(f"/api/v1/runs/{run['run_id']}/report?format=zip", headers=H)
    assert z.headers["content-type"] == "application/zip"
    assert (
        client.get(f"/api/v1/runs/{run['run_id']}/export?format=zip&trace_formats=asc", headers=H).status_code
        == 200
    )
    rep = client.post(
        "/api/v1/reports", json={"title": "API-Report", "from": "-5m", "include": {"logs": False}}, headers=H
    ).json()
    assert rep["runs"] == 1
    assert "API-Report" in client.get(f"/api/v1/reports/{rep['id']}?format=html", headers=H).text
    assert client.get(f"/api/v1/reports/{rep['id']}/attachments/trace.asc", headers=H).status_code == 200
    assert client.get(f"/api/v1/reports/{rep['id']}/attachments/..%2Fx", headers=H).status_code in (404, 422)
    assert client.post("/api/v1/reports", json={"from": "now", "to": "-5m"}, headers=H).status_code == 422
    assert client.delete(f"/api/v1/reports/{rep['id']}", headers=H).status_code == 200


def test_dashboards_api(client: TestClient):
    lst = client.get("/api/v1/dashboards", headers=H).json()
    assert lst[0]["id"] == "default"
    d = {
        "id": "bench",
        "name": "Prüfstand",
        "panels": [
            {
                "id": "btns",
                "type": "buttons",
                "title": "Aktionen",
                "buttons": [
                    {"label": "Identifikation", "action": {"type": "message", "ref": "read_identifier"}},
                    {"label": "Extended", "action": {"type": "session", "ref": "0x03", "ecu": "ecu_a"}},
                    {
                        "label": "Unlock L1",
                        "action": {"type": "unlock", "ref": 1, "ecu": "ecu_a"},
                        "color": "danger",
                    },
                    {
                        "label": "Rohes UDS",
                        "action": {
                            "type": "uds",
                            "payload": "22 ${u16(d)}",
                            "vars": {"d": 0xF101},
                            "ecu": "ecu_a",
                        },
                    },
                    {"label": "Smoke", "action": {"type": "suite", "ref": "smoke"}},
                    {"label": "Marke", "action": {"type": "marker", "ref": "Start"}},
                    {"label": "Raw", "action": {"type": "raw", "can_id": "0x700", "payload": "02 3E 00"}},
                ],
            },
            {
                "id": "vals",
                "type": "values",
                "config": {"ecu": "ecu_a", "dids": ["supply_voltage"], "refresh_ms": 1000},
            },
        ],
    }
    assert client.post("/api/v1/dashboards", json=d, headers=H).status_code == 200
    assert client.post("/api/v1/dashboards", json=d, headers=H).status_code == 409
    statuses = []
    for i in range(7):
        r = client.post(f"/api/v1/dashboards/bench/panels/btns/buttons/{i}/press", headers=H).json()
        statuses.append(r["status"])
    assert statuses == ["passed", "passed", "passed", "passed", "started", "passed", "passed"]
    r = client.post("/api/v1/dashboards/bench/panels/btns/buttons/3/press", headers=H).json()
    assert r["result"]["request"] == "22 F1 01" and r["cid"].startswith("act_")
    assert client.post("/api/v1/dashboards/bench/panels/btns/buttons/99/press", headers=H).status_code == 404
    d["name"] = "Prüfstand 2"
    assert client.put("/api/v1/dashboards/bench", json=d, headers=H).json()["name"] == "Prüfstand 2"
    bad = {
        "id": "x",
        "name": "x",
        "panels": [
            {"id": "a", "type": "buttons", "buttons": [{"label": "b", "action": {"type": "message"}}]}
        ],
    }
    assert client.post("/api/v1/dashboards", json=bad, headers=H).status_code == 422
    r = client.post(
        "/api/v1/actions/run", json={"type": "uds", "payload": "10 04", "ecu": "ecu_a"}, headers=H
    ).json()
    assert r["result"]["nrc"] == 0x12
    assert client.delete("/api/v1/dashboards/bench", headers=H).status_code == 200


def test_dashboards_from_package(client: TestClient):
    pkg = {
        "package": {"id": "dash_pkg"},
        "dashboards": [{"id": "pkg_dash", "name": "Aus Paket", "panels": []}],
    }
    client.post("/api/v1/packages", json={"content": pkg, "activate": True}, headers=H)
    d = client.get("/api/v1/dashboards/pkg_dash", headers=H).json()
    assert d["editable"] is False and d["source"] == "dash_pkg"
    assert (
        client.put("/api/v1/dashboards/pkg_dash", json={"name": "x", "panels": []}, headers=H).status_code
        == 409
    )


def test_action_status_reflects_negative_response(client: TestClient):
    r = client.post(
        "/api/v1/actions/run", json={"type": "uds", "payload": "10 04", "ecu": "ecu_a"}, headers=H
    ).json()
    assert r["status"] == "failed" and r["outcome"] == "negative"
    r = client.post(
        "/api/v1/actions/run", json={"type": "uds", "payload": "3E 00", "ecu": "ecu_a"}, headers=H
    ).json()
    assert r["status"] == "passed" and r["outcome"] == "positive"
