#!/usr/bin/env python3
"""Beispiel-Automatisierung: kompletter Testlauf allein über die API (ohne UI).

    udsbench run --demo --no-browser &          # Server starten (virtueller Bus + Testdouble)
    python examples/run_suite.py --suite full --junit report.xml

Nur Standardbibliothek – geeignet für CI und Prüfstände. Token per --token oder $UDSBENCH_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


class Client:
    def __init__(self, base: str, token: str | None) -> None:
        self.base = base.rstrip("/") + "/api/v1"
        self.token = token

    def call(self, method: str, path: str, body: object | None = None, raw: bool = False) -> object:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as exc:
            err = json.loads(exc.read().decode() or "{}").get("error", {})
            raise SystemExit(f"{method} {path} → HTTP {exc.code}: {err.get('message')} {err.get('details') or ''}") from exc
        return text if raw else json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default=os.environ.get("UDSBENCH_TOKEN"))
    ap.add_argument("--package", default="demo")
    ap.add_argument("--suite", default="full")
    ap.add_argument("--connect", action="store_true", help="Virtuellen Bus mit Testdouble verbinden")
    ap.add_argument("--junit", help="JUnit-XML hierhin schreiben")
    ap.add_argument("--json", help="JSON-Report hierhin schreiben")
    args = ap.parse_args()
    c = Client(args.url, args.token)

    # 1. Paket aktivieren
    c.call("POST", f"/packages/{args.package}/activate")
    # 2. Verbindung (falls noch nicht vorhanden)
    channels = c.call("GET", "/connection")["channels"]  # type: ignore[index]
    if args.connect and not channels:
        c.call("POST", "/connection", {"name": "default", "backend": "virtual", "options": {"bus": "vbus0"}, "simulate": True})
    # 3. Suite starten und Fortschritt verfolgen
    run = c.call("POST", f"/testsuites/{args.suite}/run", {})
    run_id = run["run_id"]  # type: ignore[index]
    print(f"Lauf {run_id} gestartet")
    while True:
        st = c.call("GET", f"/runs/{run_id}")
        if st["status"] not in ("queued", "running"):  # type: ignore[index]
            break
        s = st["summary"]  # type: ignore[index]
        print(f"  … {s['total']}/{st['planned']} Testfälle", end="\r")  # type: ignore[index]
        time.sleep(0.5)
    # 4. Ergebnis + Reports
    print(f"\nStatus: {st['status']}  {st['summary']}")  # type: ignore[index]
    for t in st["tests"]:  # type: ignore[index]
        mark = "✔" if t["status"] == "passed" else "✘"
        print(f"  {mark} {t['label']}" + (f"  – {t['message']}" if t["message"] else ""))
    if args.junit:
        with open(args.junit, "w", encoding="utf-8") as f:
            f.write(c.call("GET", f"/runs/{run_id}/report?format=junit", raw=True))  # type: ignore[arg-type]
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(c.call("GET", f"/runs/{run_id}/report?format=json", raw=True))  # type: ignore[arg-type]
    return 0 if st["status"] == "passed" else 1  # type: ignore[index]


if __name__ == "__main__":
    sys.exit(main())
