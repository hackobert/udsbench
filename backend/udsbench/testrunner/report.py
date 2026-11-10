"""Report-Export: JUnit-XML (CI) – JSON ist das native Format."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any


def to_junit(run: dict[str, Any]) -> str:
    s = run.get("summary", {})
    suites = ET.Element(
        "testsuites",
        name=f"udsbench {run.get('run_id')}",
        tests=str(s.get("total", 0)),
        failures=str(s.get("failed", 0)),
        errors=str(s.get("error", 0)),
        time=f"{(run.get('duration_ms') or 0) / 1000:.3f}",
    )
    suite = ET.SubElement(
        suites,
        "testsuite",
        name=str(run.get("name") or run.get("target")),
        tests=str(s.get("total", 0)),
        failures=str(s.get("failed", 0)),
        errors=str(s.get("error", 0)),
        skipped=str(s.get("skipped", 0)),
        time=f"{(run.get('duration_ms') or 0) / 1000:.3f}",
        timestamp=str(run.get("environment", {}).get("timestamp", "")),
    )
    props = ET.SubElement(suite, "properties")
    ET.SubElement(props, "property", name="run_id", value=str(run.get("run_id")))
    env = run.get("environment", {})
    for k in ("version", "python", "platform"):
        if k in env:
            ET.SubElement(props, "property", name=k, value=str(env[k]))
    for p in env.get("packages", []):
        ET.SubElement(props, "property", name=f"package.{p['id']}", value=f"{p['version']} ({p['hash']})")
    for t in run.get("tests", []):
        tc = ET.SubElement(
            suite,
            "testcase",
            classname=f"udsbench.{run.get('target')}",
            name=t.get("label") or t.get("name"),
            time=f"{(t.get('duration_ms') or 0) / 1000:.3f}",
        )
        status = t.get("status")
        lines = []
        for st in t.get("steps", []):
            lines.append(
                f"{'  ' * st.get('depth', 0)}[{st['status'].upper():7}] {st['name']}: "
                f"{st.get('request') or ''} -> {st.get('response') or '-'} {st.get('message') or ''}".rstrip()
            )
            for a in st.get("assertions", []):
                if not a["ok"]:
                    lines.append(
                        f"{'  ' * st.get('depth', 0)}    ✗ {a['name']}: {a['message']} (erwartet {a.get('expected')})"
                    )
        detail = "\n".join(lines)
        if status == "failed":
            el = ET.SubElement(
                tc, "failure", message=t.get("message") or "fehlgeschlagen", type="AssertionError"
            )
            el.text = detail
        elif status == "error":
            el = ET.SubElement(tc, "error", message=t.get("message") or "Fehler", type="Error")
            el.text = detail
        elif status == "skipped":
            ET.SubElement(tc, "skipped")
        out = ET.SubElement(tc, "system-out")
        out.text = detail + ("\n" + "\n".join(t.get("log", [])) if t.get("log") else "")
    ET.indent(suites)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suites, encoding="unicode")
