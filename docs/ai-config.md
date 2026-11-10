# Konfiguration aus einer Spezifikation per KI

Hersteller- und Projektspezifikationen (meist PDF) lassen sich mit einer KI in ein importierbares
Konfig-Paket übersetzen. udsbench erzeugt dafür einen Prompt aus dem **aktuellen Paketschema**:

| Teil | Inhalt |
|---|---|
| Auftrag | gewünschte Inhalte (ISO-TP, ECUs, Security, DIDs, DTCs, Routinen, Botschaften, Sequenzen, Tests, optional Simulation) |
| Regeln | nur belegte Werte, Fundstelle als YAML-Kommentar, `# TODO:`/`# PRÜFEN:` für Lücken, Hex-Schreibweise, eindeutige IDs, korrekte Verweise, **keine** Seed-to-Key-Verfahren oder Schlüssel (nur Provider-Platzhalter) |
| Feldreferenz | alle Felder mit Typ, Pflicht/Default und Beschreibung – automatisch aus den Pydantic-Modellen |
| Beispiel | gültiges Minimalpaket (wird in den Tests importiert) |
| Ausgabeformat | genau ein YAML-Codeblock, danach „Offene Punkte“ und „Zusammenfassung“ |
| Selbstprüfung | Checkliste für die KI |

## Wege

| Oberfläche | API | CLI |
|---|---|---|
| Pakete → *Konfiguration aus Spezifikation (KI)* → *Prompt kopieren* | `GET /api/v1/config/ai-prompt?package_id=&package_name=&sections=&simulation=&tests=&notes=&json_schema=&format=json\|text` | `udsbench ai-prompt [--package-id] [--sections] [--simulation] [--no-tests] [--notes] [--json-schema] [-o datei]` |
| Antwort einfügen → *Prüfen* / *Importieren* | `POST /api/v1/config/ai-check {content, do_import, activate, overwrite}` | `udsbench ai-check antwort.md [-o paket.yaml]` |
| *Korrektur-Prompt kopieren* | Feld `fix_prompt` in der Antwort von `ai-check` | Ausgabe von `ai-check` bei Fehlern |

`ai-check` extrahiert den YAML-Block aus der kompletten KI-Antwort, validiert ihn wie ein normaler
Import und listet `TODO`-/`PRÜFEN`-Stellen. Bei Fehlern enthält der Korrektur-Prompt das Paket und
die genauen Validierungsmeldungen (Pfad + Grund), damit die KI gezielt nachbessert.
Auch der normale Paketimport akzeptiert Antworten mit Markdown-Codeblöcken.

Hinweise: Ergebnis immer gegen die Spezifikation prüfen (IDs, Adressierung, Padding, Skalierung),
erst am virtuellen Bus, dann am Prüfstand. Vertrauliche Spezifikationen nur an freigegebene
KI-Dienste geben. Ausführliche Anleitung: Hilfethema „Konfiguration aus Spezifikation“.
