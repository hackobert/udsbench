"""Integrierte Hilfe: Themen (Markdown), Volltextsuche, Kontext-Zuordnung und Feld-Tooltips.

Die Themen liegen als Markdown mit Front-Matter in ``help/<sprache>/*.md``. Zusätzlich werden
Referenzthemen (NRC-Tabelle, Dienstkatalog) aus den Protokolldaten erzeugt, damit sie immer zum
Code passen. Die Suche gewichtet Titel, Schlüsselwörter, Überschriften und Fließtext.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..core.errors import NotFoundError
from ..uds.nrc import NRC_TABLE
from ..uds.services import SERVICES

HELP_DIR = Path(__file__).resolve().parent

#: Ansicht der Oberfläche → Hilfethemen (erstes = Hauptthema)
CONTEXT_TOPICS: dict[str, list[str]] = {
    "home": ["erste-schritte", "einrichtung", "tastenkuerzel", "fehlerbehebung"],
    "setup": ["einrichtung", "verbindung", "adressierung-padding"],
    "devices": ["einrichtung", "isotp-profile", "pakete-konfiguration"],
    "connection": ["verbindung", "einrichtung", "simulation", "fehlerbehebung"],
    "trace": ["trace", "dbc", "adressierung-padding", "aufzeichnungen"],
    "dbc": ["dbc", "trace", "verbindung"],
    "uds": ["uds-senden", "adressierung-padding", "nrc-referenz", "dienst-referenz"],
    "isotp": ["isotp-profile", "adressierung-padding"],
    "dids": ["dids"],
    "dtcs": ["fehlerspeicher"],
    "routines": ["routinen-transfer"],
    "messages": ["botschaften-sequenzen", "dashboards"],
    "sequences": ["botschaften-sequenzen", "tests"],
    "security": ["security", "nrc-referenz"],
    "tests": ["tests", "reports"],
    "recordings": ["aufzeichnungen"],
    "reports": ["reports", "timechart"],
    "timechart": ["timechart", "reports"],
    "dashboards": ["dashboards", "timechart"],
    "packages": ["pakete-konfiguration", "ki-konfiguration", "simulation"],
    "logs": ["logs-konsole-api"],
    "console": ["logs-konsole-api"],
}

_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)(?:\s*\{#([\w-]+)\})?\s*$", re.M)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ß", "ss")


STOPWORDS = {
    "im",
    "in",
    "der",
    "die",
    "das",
    "und",
    "ist",
    "mit",
    "von",
    "zu",
    "den",
    "dem",
    "ein",
    "eine",
    "einer",
    "wie",
    "was",
    "wo",
    "auf",
    "fur",
    "an",
    "am",
    "bei",
    "oder",
    "es",
    "ich",
    "man",
    "the",
    "of",
    "to",
}


def _words(s: str) -> list[str]:
    out: list[str] = []
    for w in re.split(r"[^\w]+", _norm(s)):
        if not w:
            continue
        out.append(w)
        if w.startswith("0x") and len(w) > 2:
            out.append(w[2:])  # "0x35" auch als "35" auffindbar
    return out


def _terms(s: str) -> list[str]:
    return [w for w in _words(s) if w not in STOPWORDS and not (w.startswith("0x") and len(w) > 2)] or _words(
        s
    )


@dataclass
class Section:
    anchor: str
    title: str
    level: int
    text: str


@dataclass
class Topic:
    id: str
    title: str
    category: str
    keywords: list[str]
    contexts: list[str]
    markdown: str
    sections: list[Section] = field(default_factory=list)
    order: int = 0
    generated: bool = False

    def summary(self) -> dict[str, Any]:
        def _prose(text: str) -> str:
            return "\n".join(
                ln for ln in text.splitlines() if not ln.lstrip().startswith(("|", "```", "-", "#"))
            )

        prose = next((p for p in (_prose(s.text) for s in self.sections) if p.strip()), "")
        first = ""
        intro = re.sub(r"\s+", " ", re.sub(r"[#*`|>_\[\]]", "", prose or first)).strip()
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "keywords": self.keywords,
            "contexts": self.contexts,
            "intro": intro[:220],
            "generated": self.generated,
            "sections": [
                {"anchor": s.anchor, "title": s.title, "level": s.level} for s in self.sections if s.level > 1
            ],
        }


def _slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", _norm(text))).strip("-")


def parse_topic(text: str, order: int = 0, generated: bool = False) -> Topic:
    meta: dict[str, Any] = {}
    m = _FRONT.match(text)
    body = text
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = text[m.end() :]
    sections: list[Section] = []
    matches = list(_HEADING.finditer(body))
    for i, h in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        title = h.group(2).strip()
        sections.append(
            Section(h.group(3) or _slug(title), title, len(h.group(1)), body[h.end() : end].strip())
        )
    # Anker-Syntax {#…} aus dem ausgelieferten Markdown entfernen
    clean = re.sub(r"\s*\{#[\w-]+\}", "", body).strip()
    kw = meta.get("keywords", "")
    keywords = [k.strip() for k in (kw.split(",") if isinstance(kw, str) else kw) if str(k).strip()]
    return Topic(
        id=str(meta.get("id") or _slug(sections[0].title if sections else "thema")),
        title=str(meta.get("title") or (sections[0].title if sections else "Hilfe")),
        category=str(meta.get("category", "Allgemein")),
        keywords=keywords,
        contexts=list(meta.get("contexts") or []),
        markdown=clean,
        sections=sections,
        order=order,
        generated=generated,
    )


def _generated_topics() -> list[Topic]:
    rows = "\n".join(f"| 0x{c:02X} | {n} | {d} |" for c, (n, d) in sorted(NRC_TABLE.items()) if c)
    nrc_md = f"""---
id: nrc-referenz
title: NRC-Referenz (Negative Response Codes)
category: Referenz
keywords: nrc, negative response, 7f, fehlercode, ablehnung, iso 14229
contexts: [uds, security]
---
# NRC-Referenz {{#nrc}}

Eine negative Antwort hat die Form `7F <SID> <NRC>`. Bedeutung der Codes nach ISO 14229-1:

| NRC | Name | Bedeutung |
|---|---|---|
{rows}
| 0x95-0xEF | reservedForSpecificConditionsNotCorrect | reserviert für spezifische Bedingungen |
| 0xF0-0xFE | vehicleManufacturerSpecificConditionsNotCorrect | herstellerspezifische Bedingung nicht erfüllt |

## Häufige Ursachen {{#ursachen}}

| NRC | Prüfen |
|---|---|
| 0x11, 0x7F | Dienst in dieser ECU bzw. Session nicht verfügbar: Session wechseln |
| 0x12, 0x7E | Subfunktion nicht unterstützt bzw. nicht in dieser Session |
| 0x13 | Länge oder Format der Anfrage falsch |
| 0x22 | Bedingungen nicht erfüllt (z. B. Fahrzeugzustand) |
| 0x24 | falsche Reihenfolge, z. B. Key ohne Seed |
| 0x31 | Wert oder Identifier außerhalb des gültigen Bereichs |
| 0x33 | Security Access erforderlich |
| 0x35, 0x36, 0x37 | falscher Key, zu viele Versuche, Wartezeit läuft |
| 0x78 | keine Ablehnung: Antwort folgt, udsbench wartet automatisch länger |
"""
    svc_rows = []
    for s in SERVICES.values():
        subs = (
            ", ".join(f"{k:02X} {v}" for k, v in sorted(s.subfunctions.items())[:12])
            if s.subfunctions
            else "–"
        )
        if s.sid == 0x27:
            subs = "ungerade = requestSeed, gerade = sendKey"
        svc_rows.append(
            f"| 0x{s.sid:02X} | {s.name} | {s.description} | {'ja' if s.sprm_allowed else 'nein'} | {subs} |"
        )
    svc_md = (
        """---
id: dienst-referenz
title: Dienst-Referenz (UDS-Services)
category: Referenz
keywords: service, sid, dienst, subfunktion, iso 14229, katalog
contexts: [uds]
---
# Dienst-Referenz {#dienste}

Positive Antworten tragen die SID + 0x40 (z. B. 0x22 → 0x62). SPRM = positive Antwort
unterdrückbar.

| SID | Dienst | Zweck | SPRM | Subfunktionen |
|---|---|---|---|---|
"""
        + "\n".join(svc_rows)
        + "\n"
    )
    return [parse_topic(nrc_md, 900, True), parse_topic(svc_md, 901, True)]


class HelpService:
    def __init__(self, lang: str = "de") -> None:
        self.lang = lang
        self.topics: dict[str, Topic] = {}
        self.tooltips: dict[str, dict[str, str]] = {}
        self._index: list[tuple[Topic, Section, dict[str, int]]] = []
        self.load()

    def load(self) -> None:
        d = HELP_DIR / self.lang
        topics: list[Topic] = []
        for i, f in enumerate(sorted(d.glob("*.md"))):
            topics.append(parse_topic(f.read_text(encoding="utf-8"), i))
        topics += _generated_topics()
        self.topics = {t.id: t for t in topics}
        tt = d / "tooltips.yaml"
        self.tooltips = yaml.safe_load(tt.read_text(encoding="utf-8")) if tt.exists() else {}
        self._build_index()

    def _build_index(self) -> None:
        idx = []
        for t in self.topics.values():
            head = _words(" ".join([t.title, *t.keywords, t.category]))
            for s in t.sections:
                counts: dict[str, int] = {}
                for w in head:
                    counts[w] = counts.get(w, 0) + 6
                for w in _words(s.title):
                    counts[w] = counts.get(w, 0) + 4
                for w in _words(s.text):
                    counts[w] = counts.get(w, 0) + 1
                idx.append((t, s, counts))
        self._index = idx

    # --------------------------------------------------------------------------------------
    def index(self) -> dict[str, Any]:
        cats: dict[str, list[dict[str, Any]]] = {}
        for t in sorted(self.topics.values(), key=lambda x: x.order):
            cats.setdefault(t.category, []).append(t.summary())
        return {
            "language": self.lang,
            "categories": [{"name": k, "topics": v} for k, v in cats.items()],
            "contexts": CONTEXT_TOPICS,
        }

    def topic(self, tid: str) -> dict[str, Any]:
        t = self.topics.get(tid)
        if t is None:
            raise NotFoundError(f"Hilfethema {tid!r} nicht gefunden")
        related = [
            self.topics[r].summary()
            for ctx in t.contexts
            for r in CONTEXT_TOPICS.get(ctx, [])
            if r in self.topics and r != tid
        ]
        seen: set[str] = set()
        related = [r for r in related if not (r["id"] in seen or seen.add(r["id"]))][:6]  # type: ignore[func-returns-value]
        return {**t.summary(), "markdown": t.markdown, "related": related}

    def context(self, ctx: str, field_key: str | None = None) -> dict[str, Any]:
        ids = (
            CONTEXT_TOPICS.get(ctx)
            or [t.id for t in self.topics.values() if ctx in t.contexts]
            or ["erste-schritte"]
        )
        out: dict[str, Any] = {
            "context": ctx,
            "topics": [self.topics[i].summary() for i in ids if i in self.topics],
        }
        out["primary"] = self.topic(ids[0]) if ids[0] in self.topics else None
        if field_key:
            tip = self.tooltips.get(f"{ctx}.{field_key}") or self.tooltips.get(field_key)
            if tip:
                out["tooltip"] = tip
        return out

    def search(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        terms = _terms(q)
        if not terms:
            return []
        hex_term = q.strip().lower().removeprefix("0x")
        results = []
        for t, s, counts in self._index:
            assert s is not None
            score = 0.0
            matched = 0
            for term in terms:
                hit: float = counts.get(term, 0)
                if not hit and len(term) >= 3:
                    hit = sum(v for k, v in counts.items() if k.startswith(term)) * 0.6
                if hit:
                    matched += 1
                    score += hit
            # nicht jedes Wort muss vorkommen, aber die Mehrheit
            if matched < max(1, -(-len(terms) * 6 // 10)):
                continue
            score *= matched / len(terms)
            # NRC-/SID-Codes direkt finden (z. B. "0x35" oder "35"), Referenz bevorzugen
            if re.fullmatch(r"[0-9a-f]{2}", hex_term) and f"0x{hex_term}" in _norm(s.text):
                score += 40 if t.category == "Referenz" else 10
            if score <= 0:
                continue
            results.append((score, t, s))
        results.sort(key=lambda r: -r[0])
        out: list[dict[str, Any]] = []
        for score, t, s in results[:limit]:
            out.append(
                {
                    "topic": t.id,
                    "topic_title": t.title,
                    "category": t.category,
                    "anchor": s.anchor,
                    "section": s.title,
                    "score": round(score, 1),
                    "snippet": _snippet(s.text, terms) or t.summary()["intro"] or s.title,
                }
            )
        return out


def _snippet(text: str, terms: list[str], width: int = 180) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # Markdown-Links → Linktext
    plain = re.sub(r"\s+", " ", re.sub(r"[#*`|>_]|-{3,}|\{#[\w-]+\}", " ", text)).strip()
    low = _norm(plain)
    pos = min((p for p in (low.find(t) for t in terms) if p >= 0), default=0)
    start = max(0, pos - width // 3)
    snip = plain[start : start + width]
    return ("… " if start else "") + snip + (" …" if start + width < len(plain) else "")


@lru_cache(maxsize=4)
def get_help(lang: str = "de") -> HelpService:
    return HelpService(lang)
