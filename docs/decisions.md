# Entscheidungen zu den offenen Punkten (Abschnitt 18 des Auftrags)

Die folgenden Punkte wurden mit den im Auftrag empfohlenen Standardwerten entschieden. Jede
Entscheidung ist ohne Architekturänderung revidierbar.

| # | Frage | Entscheidung | Begründung / Hinweis |
|---|---|---|---|
| 1 | Backend-Stack | **Python 3.11+ / FastAPI / uvicorn / Pydantic v2** | wie empfohlen; asyncio durchgängig |
| 2 | Frontend | **Vanilla TypeScript + Vite** (TS strict, keine Runtime-Abhängigkeiten) | vom Auftrag erlaubte schlanke Variante; ein Build-Schritt, statische Auslieferung durch das Backend |
| 3 | CAN-Interfaces Release 1 | **virtueller Bus** (eingebaut, mehrknotenfähig) + **python-can** (alle dort unterstützten Interfaces, z. B. SocketCAN, serielle/USB-Adapter) | Treiberwahl ausschließlich per Konfiguration (`interface`, `channel`, `bitrate` …) |
| 4 | Umfang ECU-Testdouble | konfigurierbar per Paket: Sessions/S3, Security (Seed-Länge, Provider, Fehlversuche, Sperrzeit), DIDs (Sessions/Security/Länge), DTCs inkl. Snapshot/Extended, Routinen (Sessions, Security, 0x78), Speicher, Up-/Download, Overrides (Fehlerinjektion, Verzögerung, 0x78) | deckt alle Konformitäts- und NRC-Tests ab |
| 5 | Report-/Trace-Formate | Reports **JSON** (nativ) + **JUnit-XML**; Trace **JSONL** (nativ), **CSV**, **ASC** (ASCII-Logformat), **candump-Log** | Import und Export für alle Trace-Formate |
| 6 | Authentifizierung | **lokaler API-Token** (Bearer / `X-API-Token` / `?token=` für WS/SSE); ohne Token nur an Loopback; bei Nicht-Loopback-Bindung ohne Token wird automatisch ein zufälliges Token erzeugt | Token per `UDSBENCH_TOKEN` (nicht in Dateien) |
| 7 | Lizenz / Repo-Name | **MIT**, Python-Paket/CLI **`udsbench`**; empfohlener Repository-Name `udsbench` | MIT ist freizügig, verträglich mit allen Abhängigkeiten (inkl. LGPL-3.0 von python-can als separatem Paket) und erleichtert den Einsatz in Firmen und Prüfständen. Details: `THIRD_PARTY_NOTICES.md` |
| 8 | Ein-Datei-Build | **ja, optional**: `packaging/udsbench.spec` (PyInstaller), in der CI je Plattform als Artefakt gebaut | Standardweg bleibt `pip install .` |
| 9 | Beispiel-Pakete | **Demo-Paket** (`config/packages/demo.example.yaml`, 3 simulierte ECUs) + **Vorlage für reale Anbindung** (`config/templates/real_ecu.template.yaml`) | Vorlage wird nicht automatisch geladen |

## Weitere Festlegungen

* **Eigene ISO-TP-Implementierung** statt `can-isotp`: plattformübergreifend identisches Verhalten
  (auch Windows/macOS ohne Kernel-ISO-TP), volle Kontrolle über Padding/DLC/Adressierung und
  vollständig testbar (symmetrische Encoder/Decoder als reine Funktionen).
* **Default-Padding**: aktiv mit `0xCC` (ISO-15765-2-Empfehlung) und fester DLC – überschreibbar.
* **Default-Timing**: P2 = 50 ms, P2* = 5000 ms (ISO-14229-2-Defaults), Zuschlag 100 ms.
* Konfig-Pakete, die per UI/API angelegte Objekte enthalten, landen im **Arbeitsbereich-Paket**
  `workspace` (im Datenverzeichnis, git-ignoriert).
