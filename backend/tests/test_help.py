"""Integrierte Hilfe: Themen, Suche, Kontext, Tooltips, API."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from udsbench.help.service import CONTEXT_TOPICS, HelpService
from udsbench.server import create_app

from .conftest import make_config


def test_topics_and_references_consistent():
    h = HelpService()
    assert {
        "erste-schritte",
        "uds-senden",
        "adressierung-padding",
        "security",
        "reports",
        "dashboards",
        "timechart",
        "nrc-referenz",
        "dienst-referenz",
    } <= set(h.topics)
    for ctx, ids in CONTEXT_TOPICS.items():
        assert all(i in h.topics for i in ids), ctx
    for key, tip in h.tooltips.items():
        tid, _, anchor = tip["topic"].partition("#")
        assert tid in h.topics, key
        if anchor:
            assert anchor in [s.anchor for s in h.topics[tid].sections], key
    # Querverweise help:<id> in den Texten zeigen auf existierende Themen
    import re

    for t in h.topics.values():
        for ref in re.findall(r"\(help:([\w-]+)", t.markdown):
            assert ref in h.topics, (t.id, ref)


def test_search_quality():
    h = HelpService()
    assert h.search("0x35")[0]["topic"] == "nrc-referenz"
    assert h.search("Länge im zweiten Byte")[0]["topic"] == "adressierung-padding"
    assert h.search("dashboard knopf")[0]["topic"] == "dashboards"
    assert h.search("seed key")[0]["topic"] == "security"
    assert h.search("Fehlerspeicher löschen")[0]["topic"] == "fehlerspeicher"
    assert h.search("xyzzy") == []
    assert all(r["snippet"] for r in h.search("padding"))
    assert all("](help:" not in r["snippet"] for r in h.search("NRC-Referenz"))


def test_help_api(tmp_path: Path):
    app = create_app(make_config(tmp_path), tmp_path)
    with TestClient(app) as c:
        idx = c.get("/api/v1/help").json()
        assert idx["categories"] and "uds" in idx["contexts"]
        t = c.get("/api/v1/help/topics/uds-senden").json()
        assert "Frame-Vorschau" in t["markdown"] and "{#" not in t["markdown"] and t["related"]
        ctx = c.get("/api/v1/help/context/uds?field=sprm").json()
        assert ctx["primary"]["id"] == "uds-senden" and "positive Antwort" in ctx["tooltip"]["text"]
        assert c.get("/api/v1/help/search?q=padding").json()["results"]
        assert "isotp.padding_byte" in c.get("/api/v1/help/tooltips").json()
        assert c.get("/api/v1/help/topics/nope").status_code == 404
