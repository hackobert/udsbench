---
id: logs-konsole-api
title: Logs, Konsole & API
category: Automatisierung
keywords: log, logs, audit, kommunikation, korrelation, cid, konsole, api, rest, curl, token, automatisierung, ci, websocket, openapi
contexts: [logs, console]
---
# Logs, Konsole & API

## Logs {#logs}

| Kanal | Inhalt |
|---|---|
| app | Anwendung: Start, Verbindungen, Pakete |
| comm | Kommunikation: jede UDS-Anfrage und Antwort mit Zeit; auf TRACE jeder Frame |
| audit | sicherheitsrelevante Aktionen: Seed-Anfragen, Unlock-Versuche |
| test | Testläufe Schritt für Schritt |

Jede Anfrage, jeder Unlock und jeder Testlauf erhält eine **Korrelations-ID**. Ein Klick darauf
filtert alle zugehörigen Einträge. Logs werden zusätzlich als JSON-Lines im Log-Verzeichnis
gespeichert und rotiert.

## Konsole {#konsole}

Die Konsole führt API-Aufrufe direkt aus und zeigt das passende curl-Kommando, damit Sie die API
nebenbei lernen.

| Eingabe | Wirkung |
|---|---|
| `GET /info` | Status abfragen |
| `POST /uds/request {"ecu":"ecu_a","payload":"22 F1 00"}` | beliebiger API-Aufruf |
| `uds ecu_a 22 F1 00` | Kurzform für eine UDS-Anfrage |
| `send read_identifier` | vordefinierte Botschaft senden |
| `run suite smoke` | Suite starten |
| `help` | alle Befehle |

Pfeil hoch/runter blättert im Verlauf.

## API {#api}

Alles in der Oberfläche ist über `/api/v1` erreichbar. Die vollständige Beschreibung mit
Ausprobier-Funktion finden Sie unter `/docs`.

* **Token**: `Authorization: Bearer <token>`; für WebSocket und Log-Stream `?token=`.
* **Kompletter Testlauf ohne Oberfläche**: Paket aktivieren, Suite mit `{"wait": true}` starten,
  JUnit-Report abholen. Ein fertiges Skript liegt unter `examples/run_suite.py`.
* **Live-Daten**: `/ws/trace` für Frames, `/ws/events` für Ereignisse.
