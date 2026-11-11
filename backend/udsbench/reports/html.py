"""Eigenständige HTML-Reports (eine Datei, inline CSS/SVG, druckbar, hell/dunkel)."""

from __future__ import annotations

import html
import time
from typing import Any

CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5f6b7a;--line:#d9dee6;--card:#f5f7fa;--ok:#1f8a4c;--bad:#c62f2f;--warn:#b7791f;--acc:#2f6fdb}
@media (prefers-color-scheme:dark){:root{--bg:#14181f;--fg:#e4e8ef;--muted:#9aa5b4;--line:#2c3440;--card:#1c222b;--ok:#3fbf75;--bad:#ef6464;--warn:#e0a84a;--acc:#6aa0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:16px 0 6px}.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:22px}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{background:var(--card);position:sticky;top:0}td.mono,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;word-break:break-all}.ascii{white-space:pre-wrap;opacity:.85}
.st{font-weight:600;text-transform:uppercase;font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid currentColor}
.passed,.positive{color:var(--ok)}.failed,.negative,.error,.timeout{color:var(--bad)}.skipped,.cancelled,.suppressed,.warning{color:var(--warn)}
details{border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:4px 8px}summary{cursor:pointer;font-weight:600}
.legend span{display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:12px}.legend i{width:10px;height:10px;border-radius:2px;display:inline-block}
svg text{fill:var(--muted);font-size:10px}@media print{th{position:static}details{break-inside:avoid}details[open] summary~*{display:block}}
"""

PALETTE = {
    "positive": "#2e9d5b",
    "negative": "#d64545",
    "timeout": "#b07a1c",
    "suppressed": "#8a8f99",
    "error": "#7a3fb5",
    "request": "#3b74d9",
    "FF": "#7c5cd6",
    "CF": "#4db1c4",
    "FC": "#c08a2e",
    "can": "#9aa0aa",
}
EXTRA = ["#3b74d9", "#e07b39", "#2e9d5b", "#a259c4", "#d64545", "#4db1c4", "#c0a12e", "#6b7a8f"]


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def ascii_of(hex_text: Any) -> str:
    """ASCII-Übersetzung von Hex-Bytes („62 F1 90 …“): druckbare Zeichen, sonst „·“. Leer bei Nicht-Hex."""
    if not isinstance(hex_text, str):
        return ""
    s = "".join(hex_text.split())
    if not s or len(s) % 2 or any(c not in "0123456789abcdefABCDEF" for c in s):
        return ""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "·" for b in bytes.fromhex(s))


def _ascii_html(hex_text: Any) -> str:
    a = ascii_of(hex_text)
    return f'<div class="ascii"><span class="muted">ASCII</span> {e(a)}</div>' if a else ""


def ts(t: float | None, ms: bool = True) -> str:
    if not t:
        return "–"
    s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    return s + (f".{int((t % 1) * 1000):03d}" if ms else "")


def color_for(group: str, idx: int) -> str:
    return PALETTE.get(group, EXTRA[idx % len(EXTRA)])


def stacked_chart(series: dict[str, Any], height: int = 160, title: str = "") -> str:
    """Gestapeltes Balkendiagramm (SVG) aus einem bucketize()-Ergebnis."""
    buckets = series.get("buckets") or []
    groups = list((series.get("groups") or {}).keys())
    if not buckets or not groups:
        return f'<p class="muted">{e(title)}: keine Daten im Zeitraum.</p>'
    w = 1100
    pad_l, pad_b = 34, 18
    maxv = max((b["total"] for b in buckets), default=1) or 1
    bw = (w - pad_l) / len(buckets)
    parts = [f'<svg viewBox="0 0 {w} {height + pad_b}" width="100%" role="img" aria-label="{e(title)}">']
    for frac in (0, 0.5, 1):
        y = height - frac * height
        parts.append(
            f'<line x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" stroke="currentColor" opacity=".12"/>'
            f'<text x="{pad_l - 4}" y="{y + 3:.1f}" text-anchor="end">{round(maxv * frac)}</text>'
        )
    for i, b in enumerate(buckets):
        y = height
        for gi, g in enumerate(groups):
            v = b["counts"].get(g, 0)
            if not v:
                continue
            h = v / maxv * height
            y -= h
            parts.append(
                f'<rect x="{pad_l + i * bw:.2f}" y="{y:.2f}" width="{max(bw - 0.6, 0.6):.2f}" height="{h:.2f}" '
                f'fill="{color_for(g, gi)}"><title>{e(ts(b["t"], False))} · {e(g)}: {v}</title></rect>'
            )
    for i in (0, len(buckets) // 2, len(buckets) - 1):
        parts.append(
            f'<text x="{pad_l + i * bw:.1f}" y="{height + 13}">{e(time.strftime("%H:%M:%S", time.localtime(buckets[i]["t"])))}</text>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{color_for(g, gi)}"></i>{e(g)} ({series["groups"][g]})</span>'
        for gi, g in enumerate(groups)
    )
    return f"<h3>{e(title)}</h3>" + "".join(parts) + f'<div class="legend">{legend}</div>'


def _page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>{body}"
        f'<p class="muted" style="margin-top:32px">Erstellt mit udsbench · {e(ts(time.time(), False))}</p></main></body></html>'
    )


def _tiles(items: list[tuple[str, Any, str]]) -> str:
    return (
        '<div class="grid">'
        + "".join(
            f'<div class="tile"><span class="muted">{e(k)}</span><b class="{c}">{e(v)}</b></div>'
            for k, v, c in items
        )
        + "</div>"
    )


def run_section(run: dict[str, Any], open_failed: bool = True) -> str:
    s = run.get("summary", {})
    out = [
        f'<h2>Testlauf {e(run.get("name"))} <span class="st {e(run.get("status"))}">{e(run.get("status"))}</span></h2>',
        f'<p class="muted mono">{e(run.get("run_id"))} · {e(run.get("kind"))} {e(run.get("target"))} · '
        f"{e(ts(run.get('started')))} → {e(ts(run.get('finished')))} · {e(run.get('duration_ms'))} ms</p>",
        _tiles(
            [
                ("Gesamt", s.get("total", 0), ""),
                ("Bestanden", s.get("passed", 0), "passed"),
                ("Fehlgeschlagen", s.get("failed", 0), "failed"),
                ("Fehler", s.get("error", 0), "error"),
            ]
        ),
    ]
    out.append("<table><tr><th>Test</th><th>Status</th><th>Dauer</th><th>Meldung</th></tr>")
    for t in run.get("tests", []):
        out.append(
            f'<tr><td>{e(t.get("label"))}</td><td><span class="st {e(t.get("status"))}">{e(t.get("status"))}</span></td>'
            f"<td>{e(round(t.get('duration_ms') or 0, 1))} ms</td><td>{e(t.get('message'))}</td></tr>"
        )
    out.append("</table>")
    for t in run.get("tests", []):
        is_open = " open" if open_failed and t.get("status") != "passed" else ""
        out.append(
            f'<details{is_open}><summary><span class="st {e(t.get("status"))}">{e(t.get("status"))}</span> {e(t.get("label"))}</summary>'
        )
        out.append(
            "<table><tr><th>Schritt</th><th>Status</th><th>ECU</th><th>Request</th><th>Response</th><th>Zeit</th><th>Assertions</th></tr>"
        )
        for st in t.get("steps", []):
            asserts = "<br>".join(
                f'<span class="{"passed" if a["ok"] else "failed"}">{"✔" if a["ok"] else "✘"} {e(a["name"])}: '
                f"{e(a['message'])}{' (erwartet ' + e(a.get('expected')) + ')' if not a['ok'] and a.get('expected') is not None else ''}</span>"
                for a in st.get("assertions", [])
            )
            indent = "&nbsp;" * 3 * int(st.get("depth") or 0)
            out.append(
                f'<tr><td>{indent}{e(st.get("name"))}<div class="muted">{e(st.get("message"))}</div></td>'
                f'<td><span class="st {e(st.get("status"))}">{e(st.get("status"))}</span></td><td>{e(st.get("ecu"))}</td>'
                f'<td class="mono">{e(st.get("request"))}</td><td class="mono">{e(st.get("response"))}{_ascii_html(st.get("response"))}</td>'
                f"<td>{e(st.get('elapsed_ms'))}</td><td>{asserts}</td></tr>"
            )
        out.append("</table>")
        if t.get("log"):
            out.append('<pre class="mono">' + e("\n".join(t["log"])) + "</pre>")
        out.append("</details>")
    env = run.get("environment") or {}
    if env:
        pk = ", ".join(f"{p['id']} {p['version']} ({p['hash']})" for p in env.get("packages", []))
        out.append(
            f'<p class="muted">Umgebung: udsbench {e(env.get("version"))} · Python {e(env.get("python"))} · '
            f"{e(env.get('platform'))} · Pakete: {e(pk)}</p>"
        )
    return "".join(out)


def render_run(run: dict[str, Any]) -> str:
    return _page(
        f"Testreport {run.get('name')}", f"<h1>Testreport: {e(run.get('name'))}</h1>" + run_section(run)
    )


def render_manual(rep: dict[str, Any]) -> str:
    b: list[str] = [
        f"<h1>{e(rep.get('title'))}</h1>",
        f'<p class="muted">Zeitraum {e(ts(rep["from"]))} → {e(ts(rep["to"]))} · erstellt {e(ts(rep.get("created"), False))}'
        f"{' · ' + e(rep['author']) if rep.get('author') else ''}{' · ECU ' + e(rep['ecu']) if rep.get('ecu') else ''}</p>",
    ]
    if rep.get("notes"):
        b.append('<div class="tile" style="white-space:pre-wrap">' + e(rep["notes"]) + "</div>")
    st = rep.get("stats") or {}
    totals = st.get("uds_totals") or {}
    b.append("<h2>Übersicht</h2>")
    b.append(
        _tiles(
            [
                ("UDS-Anfragen", st.get("uds_requests", 0), ""),
                ("positiv", totals.get("positive", 0), "positive"),
                ("negativ", totals.get("negative", 0), "negative"),
                ("Timeout", totals.get("timeout", 0), "timeout"),
                ("CAN-Frames", st.get("frames", 0), ""),
                ("Testläufe", len(rep.get("runs") or []), ""),
                ("Warnungen/Fehler", st.get("log_problems", 0), "warning"),
            ]
        )
    )
    if st.get("latency"):
        lat = st["latency"]
        b.append(
            f'<p class="muted">Antwortzeit: Ø {e(lat.get("avg"))} ms · min {e(lat.get("min"))} ms · max {e(lat.get("max"))} ms</p>'
        )
    if st.get("uds_by_type"):
        b.append(stacked_chart(st["uds_by_type"], title="UDS-Antworten nach Typ"))
    if st.get("uds_by_service"):
        b.append(stacked_chart(st["uds_by_service"], title="UDS-Anfragen nach Service"))
    if st.get("frames_by_type"):
        b.append(stacked_chart(st["frames_by_type"], title="CAN-Frames nach Typ"))
    if st.get("nrc_counts"):
        b.append(
            "<h3>Negative Responses</h3><table><tr><th>NRC</th><th>Anzahl</th></tr>"
            + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in st["nrc_counts"].items())
            + "</table>"
        )
    if st.get("services"):
        b.append(
            "<h3>Services</h3><table><tr><th>Service</th><th>Anzahl</th></tr>"
            + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in st["services"].items())
            + "</table>"
        )
    for run in rep.get("runs") or []:
        b.append(run_section(run, open_failed=False))
    ev = rep.get("events") or []
    if ev:
        b.append(
            f"<h2>Ereignisse ({len(ev)})</h2><table><tr><th>Zeit</th><th>Thema</th><th>Typ</th><th>ECU</th><th>Details</th></tr>"
        )
        for x in ev[-2000:]:
            detail = x.get("text") or x.get("msg") or x.get("request") or x.get("name") or ""
            if x.get("nrc_name"):
                detail = f"{detail} → {x['nrc_name']}"
            b.append(
                f'<tr><td class="mono">{e(ts(x["ts"]))}</td><td>{e(x["topic"])}</td><td class="{e(x.get("type"))}">{e(x.get("type"))}</td>'
                f'<td>{e(x.get("ecu"))}</td><td class="mono">{e(detail)}</td></tr>'
            )
        b.append("</table>")
    msgs = rep.get("messages") or []
    if msgs:
        b.append(
            f"<h2>UDS-Nachrichten-Trace ({len(msgs)})</h2><table><tr><th>Zeit</th><th>ECU</th><th>Richtung</th><th>Nutzlast</th><th>Interpretation</th></tr>"
        )
        for m in msgs[-3000:]:
            b.append(
                f'<tr><td class="mono">{e(ts(m.get("ts")))}</td><td>{e(m.get("ecu"))}</td><td>{e(m.get("role"))}</td>'
                f'<td class="mono">{e(m.get("payload"))}{_ascii_html(m.get("payload"))}</td><td class="{e(m.get("uds"))}">{e(m.get("text"))}</td></tr>'
            )
        b.append("</table>")
    att = rep.get("attachments") or []
    if att:
        b.append(
            "<h2>Anhänge</h2><ul>"
            + "".join(
                f'<li class="mono">{e(a["name"])} – {e(a.get("description"))} ({e(a.get("size"))} Byte)</li>'
                for a in att
            )
            + '</ul><p class="muted">Im ZIP-Export enthalten.</p>'
        )
    return _page(rep.get("title") or "Report", "".join(b))
