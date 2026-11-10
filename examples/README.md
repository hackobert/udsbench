# API-Beispiele

| Datei | Inhalt |
|---|---|
| `curl.sh` | Einzelaufrufe mit curl (Verbinden, UDS-Request, Frame-Vorschau, Unlock, DIDs, DTCs, Suite + JUnit, Aufzeichnung, Logs) |
| `run_suite.py` | Vollständiger CI-Ablauf nur mit der Python-Standardbibliothek: Paket aktivieren → Suite starten → Fortschritt pollen → JUnit/JSON speichern, Exit-Code 0/1 |
| `ci-github-actions.yml` | Ausschnitt: udsbench in einer CI-Pipeline gegen das Testdouble laufen lassen |

```bash
udsbench run --demo --no-browser &
python examples/run_suite.py --suite full --junit report.xml --json report.json
```
