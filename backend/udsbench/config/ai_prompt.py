"""Prompt-Generator: Konfig-Paket aus einer Hersteller-/Projektspezifikation per KI erstellen lassen.

Der Prompt wird aus dem tatsächlichen Paketschema erzeugt (Feldreferenz, Typen, Defaults), damit
er immer zur installierten Version passt. Dazu gehören feste Regeln (nichts erfinden, Unklares als
TODO kennzeichnen, keine geheimen Verfahren nachbauen), ein kurzes Beispiel und das genaue
Ausgabeformat. Ein zweiter Prompt spielt Validierungsfehler zur Korrektur an die KI zurück.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from .. import __version__
from .schema import Package

# Abschnitte, die in der Feldreferenz erscheinen (Reihenfolge = Lesereihenfolge)
SECTION_DEFS: list[tuple[str, str]] = [
    ("PackageMeta", "package"),
    ("IsoTpProfile", "isotp_profiles.<name>"),
    ("PaddingConfig", "isotp_profiles.<name>.padding"),
    ("IsoTpTimeouts", "isotp_profiles.<name>.timeouts"),
    ("EcuDef", "ecus[]"),
    ("SessionDef", "ecus[].sessions[]"),
    ("UdsTiming", "ecus[].timing"),
    ("TesterPresentConfig", "ecus[].tester_present"),
    ("SecurityLevelDef", "ecus[].security_levels[]"),
    ("SecurityProviderDef", "security_providers[]"),
    ("DidDef", "catalogs.dids[]"),
    ("BitField", "catalogs.dids[].bits[]"),
    ("DtcDef", "catalogs.dtcs[]"),
    ("RoutineDef", "catalogs.routines[]"),
    ("RoutineField", "catalogs.routines[].start_params[] / result_fields[]"),
    ("MessageDef", "messages[]"),
    ("SequenceDef", "sequences[]"),
    ("Step", "sequences[].steps[] / tests[].steps[]"),
    ("Expect", "<step>.expect"),
    ("TestDef", "tests[]"),
    ("SuiteDef", "testsuites[]"),
    ("SimEcuConfig", "simulation.ecus[]"),
    ("SimDid", "simulation.ecus[].dids[]"),
    ("SimDtc", "simulation.ecus[].dtcs[]"),
    ("SimRoutine", "simulation.ecus[].routines[]"),
    ("SimSecurityLevel", "simulation.ecus[].security[]"),
]

SECTIONS_ALL = [
    "isotp",
    "ecus",
    "security",
    "dids",
    "dtcs",
    "routines",
    "messages",
    "sequences",
    "tests",
    "simulation",
]


def _type_str(p: dict[str, Any], defs: dict[str, Any]) -> str:
    if "$ref" in p:
        return p["$ref"].split("/")[-1]
    if "enum" in p:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in p["enum"])
    if "const" in p:
        return json.dumps(p["const"])
    if "anyOf" in p:
        parts = [_type_str(x, defs) for x in p["anyOf"]]
        return " | ".join(dict.fromkeys(parts))
    t = p.get("type")
    if t == "array":
        return f"list[{_type_str(p.get('items', {}), defs)}]"
    if t == "object":
        ap = p.get("additionalProperties")
        if isinstance(ap, dict) and ap:
            return f"map[str, {_type_str(ap, defs)}]"
        return "map"
    return {"integer": "int", "number": "float", "string": "str", "boolean": "bool", "null": "null"}.get(
        str(t), str(t or "any")
    )


def field_reference(sections: list[str] | None = None) -> str:
    """Kompakte Feldreferenz aller relevanten Schema-Objekte (aus dem Live-Schema erzeugt)."""
    schema = Package.model_json_schema(by_alias=True)
    defs = schema.get("$defs", {})
    want = set(sections or SECTIONS_ALL)
    skip = set()
    if "simulation" not in want:
        skip |= {"SimEcuConfig", "SimDid", "SimDtc", "SimRoutine", "SimSecurityLevel"}
    if "tests" not in want:
        skip |= {"TestDef", "SuiteDef"}
    if "sequences" not in want and "tests" not in want:
        skip |= {"Step", "Expect", "SequenceDef"}
    if "routines" not in want:
        skip |= {"RoutineDef", "RoutineField"}
    lines: list[str] = []
    for name, path in SECTION_DEFS:
        if name in skip or name not in defs:
            continue
        d = defs[name]
        req = set(d.get("required", []))
        lines.append(f"\n### {path}  ({name})")
        if d.get("description"):
            lines.append(d["description"].strip().splitlines()[0])
        for fname, p in d.get("properties", {}).items():
            typ = _type_str(p, defs)
            if "PlainSerializer" in typ:
                typ = "hex"
            flag = (
                "PFLICHT"
                if fname in req
                else (
                    f"Default {json.dumps(p['default'], ensure_ascii=False)}"
                    if "default" in p
                    else "optional"
                )
            )
            desc = (p.get("description") or "").strip()
            lines.append(f"- `{fname}`: {typ} – {flag}" + (f" – {desc}" if desc else ""))
    return "\n".join(lines).strip()


EXAMPLE = """\
schema_version: 1
package:
  id: project_x_ecu1          # nur A-Z a-z 0-9 _ . -
  name: Projekt X – Steuergerät 1
  version: 0.1.0
  description: Erstellt aus Spezifikation "<Dokumenttitel>", Revision <Rev>, Stand <Datum>

isotp_profiles:
  ecu1_physical:
    channel: default
    tx_id: 0x18DA10F1          # Spez. Kap. 3.2: Request-ID
    rx_id: 0x18DAF110          # Spez. Kap. 3.2: Response-ID
    functional_id: 0x18DB33F1
    extended_id: true          # 29-Bit-Identifier
    addressing: normal
    padding: {enabled: true, byte: 0xFF}   # Spez.: "unbenutzte Bytes = FFh"
    dlc_mode: fixed
    block_size: 0
    st_min: 0x00
    timeouts: {n_as: 1000, n_ar: 1000, n_bs: 1000, n_cr: 1000}

security_providers:
  - id: ecu1_keygen
    type: native               # TODO: vom Anwender bereitzustellen – Verfahren laut Spez. vertraulich
    description: Seed-Key laut Spez. Kap. 7.4 (Bibliothek lokal bereitstellen)
    params:
      library: TODO_keygen_library.so
      function: TODO_FunctionName
      return: {type: int, success: 0}
      key_buffer_size: 64
      args: [seed_ptr, {seed_len: uint32}, {level: uint32}, key_ptr, {key_buffer_size: uint32}, key_len_ptr]

ecus:
  - id: ecu1
    name: Steuergerät 1
    isotp: ecu1_physical
    functional_group: vehicle
    sessions:
      - {id: 0x01, name: defaultSession}
      - {id: 0x02, name: programmingSession}
      - {id: 0x03, name: extendedDiagnosticSession}
    timing: {p2_ms: 50, p2_star_ms: 5000, margin_ms: 100, max_response_pending: 20}
    security_levels:
      - {level: 0x01, name: Level 1 (Service), provider: ecu1_keygen, session: 0x03}

catalogs:
  dids:
    - {id: 0xF190, name: vin, type: ascii, length: 17, description: Fahrzeug-Identnummer}
    - {id: 0x0101, name: supply_voltage, type: uint, length: 2, scale: 0.01, unit: V, description: "Spez. Tab. 12"}
    - {id: 0x0102, name: operating_state, type: enum, length: 1, enum: {0: "off", 1: "init", 2: "run", 3: "fault"}}
  dtcs:
    - {code: 0x5E1A00, name: sensor_1_open_circuit, description: "Sensor 1 Leitungsunterbrechung"}
  routines:
    - id: 0x0203
      name: self_test
      result_fields: [{name: result, type: enum, length: 1, enum: {0: passed, 1: failed}}]

messages:
  - {id: read_vin, name: VIN lesen, ecu: ecu1, payload: "22 F1 90", expect: {positive: true}}

tests:
  - id: read_vin_positive
    name: VIN lesbar (Spez. Kap. 6.1)
    ecu: ecu1
    steps:
      - {send: {message: read_vin}, expect: {positive: true, length: 20}}
  - id: write_without_unlock
    name: Schreiben ohne Security Access wird abgelehnt
    ecu: ecu1
    steps:
      - {session: 0x03}
      - {send: {payload: "2E 01 02 01"}, expect: {nrc: 0x33}}
    teardown:
      - {session: 0x01, expect: {}}

testsuites:
  - {id: spec_conformance, name: Spezifikationsprüfung ECU 1, ecu: ecu1, tests: [read_vin_positive, write_without_unlock]}
"""


RULES = """\
1. **Nur belegte Angaben.** Übernimm ausschließlich Werte, die in der Spezifikation stehen. Erfinde
   keine CAN-IDs, DIDs, Längen, Skalierungen, Sessions, NRCs oder Timings. Fehlt eine Angabe, nutze
   den Default des Schemas oder lass das Feld weg und schreibe einen Kommentar `# TODO: …`.
2. **Quellen nennen.** Setze hinter jeden aus der Spezifikation übernommenen Wert einen kurzen
   YAML-Kommentar mit Fundstelle (Kapitel, Tabelle, Seite), z. B. `# Spez. Tab. 4.2`.
3. **Unklarheiten kennzeichnen.** Widersprüche, Interpretationen und Lücken kommen als Kommentar
   `# PRÜFEN: …` direkt an die Stelle und gesammelt in den Abschnitt „Offene Punkte“ (siehe Ausgabeformat).
4. **Keine geheimen Verfahren.** Seed-to-Key-Algorithmen, Schlüssel, Passwörter oder Masken werden
   **nicht** nachgebaut und **nicht** als Klartext eingetragen. Lege einen Provider vom Typ `native`
   oder `script` mit `TODO_`-Platzhaltern an; Zugangsdaten nur als `${ENV:NAME}`.
5. **Hex-Schreibweise.** CAN-IDs, DIDs, RIDs, DTCs, Sessions, Security-Level und Bytes als Hex mit
   `0x`-Präfix (`0x7E0`, `0xF190`). Nutzlasten in `payload` als Hex-Bytes mit Leerzeichen (`"22 F1 90"`).
6. **IDs.** Objekt-IDs (`package.id`, ECU-, Profil-, Botschafts-, Sequenz-, Test-IDs, DID-Namen)
   in `snake_case`, nur `A-Z a-z 0-9 _ . -`, eindeutig. Verweise müssen exakt passen
   (`ecus[].isotp` → Schlüssel in `isotp_profiles`, `security_levels[].provider` → `security_providers[].id`,
   Tests → `messages`/`sequences`, Suiten → `tests`).
7. **ISO-TP genau abbilden.** Adressierungsart (normal/extended/mixed) mit Adressbytes, 11/29 Bit,
   Padding-Wert und ob Frames immer auf 8 Byte aufgefüllt werden (`dlc_mode: fixed`), Blocksize,
   STmin, Timeouts N_As/N_Ar/N_Bs/N_Cr, CAN-FD. PCI/Längenbytes **nicht** in Nutzlasten schreiben –
   die erzeugt das Tool.
8. **Security-Level.** `level` ist immer die ungerade requestSeed-Subfunktion (0x01, 0x03 …), nie
   die sendKey-Subfunktion. Wenn die Spezifikation verlangt, dass Security Access nur in einer
   bestimmten Session erlaubt ist, trage `session` ein.
9. **Datentypen der DIDs.** Wähle `type` passend (uint/int/float32/float64/ascii/utf8/bcd/enum/
   bitfield/bool/hex), setze `length` in Byte, `scale`/`offset`/`unit` gemäß Formel
   „physikalisch = roh × scale + offset“, `byteorder` (Default big), `access` (read/write/readwrite),
   Wertebereiche als `min`/`max` (physikalisch). Bitfelder über `bits` (Bit 0 = LSB des Gesamtwerts).
10. **Tests aus der Spezifikation.** Erzeuge für die geforderten Verhaltensweisen Testfälle:
    positive Fälle (Lesen, Session-Wechsel, Routinen) und negative Fälle mit dem erwarteten NRC
    (z. B. falsche Länge → 0x13, Schreiben ohne Unlock → 0x33, nicht unterstützte Subfunktion →
    0x12). Jeder Test nennt die Fundstelle im Namen oder in `description`. Nach Session-Wechseln
    in `teardown` zurück in die Default Session (`{session: 0x01, expect: {}}`).
11. **Kein Schema-Erfinden.** Verwende nur die Felder aus der Feldreferenz. Unbekannte Felder führen
    zum Ablehnen des Imports (`extra` ist verboten). Herstellerspezifische Informationen, für die es
    kein Feld gibt, gehören in `description` oder in Kommentare.
12. **Simulation optional.** Lege `simulation` nur an, wenn ausdrücklich gewünscht. Dann bildet das
    Testdouble das spezifizierte Verhalten nach (Sessions, DIDs mit Beispielwerten, DTCs, Routinen,
    Security mit `provider: demo`, weil das echte Verfahren nicht im Tool liegt).
"""


def build_prompt(
    *,
    package_id: str = "",
    package_name: str = "",
    sections: list[str] | None = None,
    with_simulation: bool = False,
    with_tests: bool = True,
    notes: str = "",
    include_json_schema: bool = False,
) -> str:
    secs = list(sections or SECTIONS_ALL)
    if not with_simulation and "simulation" in secs:
        secs.remove("simulation")
    if not with_tests and "tests" in secs:
        secs.remove("tests")
    wanted = {
        "isotp": "ISO-TP-Profile (CAN-IDs, Adressierung, Padding, Timing der Transportschicht)",
        "ecus": "ECU-Definitionen mit Sessions, UDS-Timing (P2/P2*), TesterPresent",
        "security": "Security-Level und Provider-Platzhalter (ohne geheime Verfahren)",
        "dids": "DID-Katalog mit Datentypen, Skalierung, Einheiten, Zugriff",
        "dtcs": "DTC-Katalog mit Beschreibung",
        "routines": "Routinen-Katalog mit Parametern und Ergebnisfeldern",
        "messages": "vordefinierte Botschaften für die wichtigsten Abfragen",
        "sequences": "Sequenzen für wiederkehrende Abläufe (z. B. Session → Security Access → Schreiben)",
        "tests": "Tests und eine Testsuite für das spezifizierte Verhalten inkl. Negativfälle",
        "simulation": "Simulation (ECU-Testdouble) mit dem spezifizierten Verhalten",
    }
    task_list = "\n".join(f"- {wanted[s]}" for s in secs if s in wanted)
    meta = []
    if package_id:
        meta.append(f"- Verwende `package.id: {package_id}`.")
    if package_name:
        meta.append(f"- Verwende `package.name: {package_name}`.")
    if notes.strip():
        meta.append(f"- Zusätzliche Hinweise des Anwenders: {notes.strip()}")
    meta_txt = ("\n**Vorgaben des Anwenders**\n" + "\n".join(meta) + "\n") if meta else ""
    schema_block = ""
    if include_json_schema:
        schema_block = (
            "\n## Anhang: vollständiges JSON-Schema\n\n```json\n"
            + json.dumps(Package.model_json_schema(by_alias=True), ensure_ascii=False, separators=(",", ":"))
            + "\n```\n"
        )
    return f"""# Auftrag: udsbench-Konfigurationspaket aus einer Spezifikation erstellen

Du bist Diagnose-Ingenieur für UDS (ISO 14229) über CAN (ISO-TP, ISO 15765-2). Ich gebe dir die
Spezifikation eines Steuergeräts (angehängt bzw. im Anschluss an diesen Text). Erstelle daraus ein
**Konfigurationspaket für das Diagnose- und Testwerkzeug udsbench** (Version {__version__}) als YAML.
Das Paket wird ohne Nacharbeit über „Pakete → Importieren“ eingelesen und streng gegen das unten
beschriebene Schema validiert. Unbekannte Felder, falsche Typen oder kaputte Verweise führen zur
Ablehnung.

## Was das Paket enthalten soll

{task_list}
{meta_txt}
## Regeln

{RULES}
## Ausgabeformat (genau einhalten)

1. **Ein einziger YAML-Codeblock** (```yaml … ```) mit dem vollständigen Paket. Keine Auslassungen
   wie „…“ oder „usw.“ – wenn es zu lang wird, priorisiere ISO-TP, ECUs, Security, DIDs, DTCs und
   kennzeichne Weggelassenes unter „Offene Punkte“.
2. Danach ein Abschnitt **„Offene Punkte“** als Markdown-Liste: fehlende oder widersprüchliche
   Angaben, Annahmen, Platzhalter (`TODO_…`), die der Anwender ergänzen muss, jeweils mit Fundstelle.
3. Danach ein Abschnitt **„Zusammenfassung“** mit Anzahl ECUs, DIDs, DTCs, Routinen, Tests.

## Struktur des Pakets (oberste Ebene)

```yaml
schema_version: 1
package: {{...}}            # Pflicht
isotp_profiles: {{<name>: {{...}}}}
security_providers: [...]
ecus: [...]
catalogs: {{dids: [...], dtcs: [...], routines: [...]}}
messages: [...]
sequences: [...]
tests: [...]
testsuites: [...]
simulation: {{ecus: [...]}}   # optional
dashboards: [...]           # optional, weglassen
```

## Feldreferenz (aus dem Schema der installierten Version erzeugt)

Typen: `int` akzeptiert Dezimal oder Hex-String (`"0x7E0"`), `hex` = Hex-Bytes als String
(`"01 02 FF"`), `map[str, X]` = Mapping. „PFLICHT“ muss gesetzt werden, sonst gilt der Default.

{field_reference(secs)}

### Schritte (`steps[]`) – genau **eine** Aktion je Schritt

| Aktion | Beispiel |
|---|---|
| send | `{{send: {{message: read_vin}}}}` oder `{{send: {{payload: "22 F1 90"}}}}` |
| session / reset | `{{session: 0x03}}`, `{{reset: 0x01}}` |
| unlock | `{{unlock: 0x01}}` (Seed anfordern, Key per Provider, Key senden) |
| request_seed / compute_key / send_key | Einzelschritte des Security Access |
| read_did / write_did | `{{read_did: vin}}`, `{{write_did: {{did: supply_limit, value: 12.5}}}}` |
| io_control | `{{io_control: {{did: 0x0300, parameter: 0x03, value: 50}}}}` |
| read_dtc / clear_dtc | `{{read_dtc: {{subfunction: 0x02, mask: 0xFF}}}}`, `{{clear_dtc: 0xFFFFFF}}` |
| routine | `{{routine: {{id: self_test, action: start}}}}` |
| wait / set / log / assert | `{{wait: 100}}`, `{{set: {{n: 1}}}}`, `{{log: "…"}}`, `{{assert: "n == 1"}}` |
| if / repeat / sequence | Bedingung, Schleife, Unter-Sequenz |

Erwartungen (`expect`): `positive`, `nrc` (Zahl oder Name, auch Liste), `response` (Muster mit
`??` und `*`), `response_prefix`, `length`, `max_time_ms`, `no_response`, `fields`, `expr`.
Ohne `expect` erwarten Komfortschritte eine positive Antwort; `expect: {{}}` schaltet Prüfungen ab.

## Beispiel (verkürzt, neutrale Platzhalterwerte)

```yaml
{EXAMPLE}```

## Selbstprüfung vor der Ausgabe

- [ ] Jede ECU verweist auf ein vorhandenes ISO-TP-Profil, jedes Security-Level auf einen vorhandenen Provider.
- [ ] Alle IDs sind eindeutig; keine doppelten DIDs, DTCs, Routinen.
- [ ] Security-Level sind ungerade (requestSeed); kein Seed-Key-Verfahren und kein Schlüssel im Klartext.
- [ ] CAN-IDs passen zur Bitbreite (11 Bit ≤ 0x7FF, sonst `extended_id: true`).
- [ ] Bei extended/mixed Adressierung ist `tx_address_extension` gesetzt.
- [ ] Nutzlasten enthalten keine PCI-/Längenbytes und kein Padding.
- [ ] Jeder Wert aus der Spezifikation hat einen Quellenkommentar; Unsicheres ist mit `# PRÜFEN:` markiert.
- [ ] Nur Felder aus der Feldreferenz verwendet.
{schema_block}
---
Spezifikation folgt / ist angehängt.
"""


def build_fix_prompt(content: str, errors: list[dict[str, Any]] | list[str], message: str = "") -> str:
    """Korrektur-Prompt: KI-Antwort + Validierungsfehler zurück an die KI."""
    lines = []
    for e in errors:
        if isinstance(e, dict):
            lines.append(f"- `{e.get('loc', '')}`: {e.get('msg', '')}")
        else:
            lines.append(f"- {e}")
    err_txt = "\n".join(lines) or f"- {message}"
    return f"""# Korrektur: udsbench-Konfigurationspaket

Der Import des von dir erzeugten Pakets in udsbench ist fehlgeschlagen. Behebe **nur** die
folgenden Fehler, ändere sonst nichts, und gib wieder das **vollständige** Paket als einen einzigen
YAML-Codeblock aus, gefolgt von „Offene Punkte“. Halte dich weiterhin an alle Regeln und die
Feldreferenz aus dem ursprünglichen Auftrag (keine erfundenen Werte, keine unbekannten Felder).

## Fehlermeldungen des Validators

{message + chr(10) if message else ""}{err_txt}

Hinweise zum Lesen: `loc` ist der Pfad im Paket, z. B. `ecus.0.isotp` = erstes Element von `ecus`,
Feld `isotp`. „Extra inputs are not permitted“ = Feld existiert im Schema nicht.

## Bisheriges Paket

```yaml
{content.strip()}
```
"""


def extract_yaml(text: str) -> str:
    """Holt den YAML-Inhalt aus einer KI-Antwort (Codeblock ```yaml … ``` oder reiner Text)."""
    import re

    blocks = re.findall(r"```(?:ya?ml|json)?[ \t]*\n(.*?)```", text, re.S | re.I)
    if blocks:
        # größter Block, der wie ein Paket aussieht
        cands = [b for b in blocks if "package" in b] or blocks
        return max(cands, key=len)
    return text


def dump_example() -> dict[str, Any]:
    return yaml.safe_load(EXAMPLE)  # type: ignore[no-any-return]
