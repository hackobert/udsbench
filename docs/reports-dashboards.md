# Reports, Timechart & Dashboards

## Ereignis-Historie

Alle UDS-Anfragen (Typ positiv/negativ/Timeout/unterdrückt, Service, NRC, Antwortzeit, ECU),
Session- und Security-Wechsel, Testläufe, Verbindungen, ISO-TP-Fehler, Warnungen/Fehler aus den
Logs sowie manuelle **Markierungen** werden mit Zeitstempel in der Historie abgelegt (Speicher +
`data/history/events-YYYY-MM-DD.jsonl`, damit auch frühere Zeiträume nach einem Neustart
auswertbar sind).

| Route | Zweck |
|---|---|
| `GET /stats/timeseries?metric=uds\|frames\|events&group_by=…&from=-5m&to=now&bucket_s=&ecu=` | Zählung je Zeit-Bucket und Gruppe (Timechart), inkl. Ø/max Antwortzeit |
| `GET /stats/summary?from=&to=&ecu=` | Kennzahlen: Anfragen, Typen, Services, NRCs, Latenz, Frames |
| `GET /events?from=&to=&topics=&types=&ecu=` | Ereignis-Zeitleiste |
| `POST /events/marker {text}` | Markierung setzen |

Zeitangaben: Epoch-Sekunden, ISO-8601 oder relativ (`-30s`, `-15m`, `-2h`, `now`).
`group_by` für UDS: `type`, `service`, `ecu`, `nrc_name`, `sid`; für Frames: `type`
(request/positive/negative/FF/CF/FC/can), `dir`, `ecu`, `id`, `channel`.

## Test-Reports exportieren

`GET /runs/{id}/report?format=json|junit|html|zip`

* **HTML** – eigenständige, druckbare Datei mit Zusammenfassung, Schritten, Requests/Responses und
  Assertions (erwartet vs. tatsächlich), Umgebung und Paketversionen.
* **ZIP** – `report.json`, `report.junit.xml`, `report.html`, die **Traces des Laufzeitraums**
  (`trace.asc`, `trace.csv`, `trace.jsonl`), die Logs des Laufs (über die Korrelations-ID) und die
  Ereignisse. Alternativ `GET /runs/{id}/export?format=zip&trace_formats=asc,candump`.

## Manuelle Reports über einen Zeitbereich

```bash
curl -X POST localhost:8765/api/v1/reports -H 'Content-Type: application/json' -d '{
  "title": "Prüfstand Lauf 12", "from": "2026-11-10T13:00:00", "to": "2026-11-10T13:30:00",
  "ecu": "ecu_a", "notes": "Spannungseinbruch bei 13:12", "trace_formats": ["asc", "csv"],
  "include": {"stats": true, "events": true, "runs": true, "messages": true, "frames": true, "logs": true, "recordings": true}}'
```

Inhalt: Kennzahlen und Diagramme (UDS nach Typ und Service, Frames nach Typ), NRC-Statistik,
Testläufe im Zeitraum (oder `run_ids`), Ereignis-Zeitleiste, rekonstruierter UDS-Trace und als
**Anhänge** die CAN-Traces (aus dem Live-Puffer, ergänzt um gespeicherte Aufzeichnungen im
Zeitraum), `uds_messages.csv`, `logs.jsonl` (maskiert), `events.jsonl` und JUnit je Lauf.
Abruf: `GET /reports`, `GET /reports/{id}?format=json|html|zip`,
`GET /reports/{id}/attachments/{name}`, `DELETE /reports/{id}`. Ablage:
`reports/manual/<id>/` (git-ignoriert).

## Dashboards

Eigene Oberflächen aus Panels in einem 12-Spalten-Raster – gespeichert in
`data/dashboards.json` oder mitgeliefert in Konfig-Paketen (`dashboards:`; schreibgeschützt, in
der UI duplizierbar). Beispiel: `demo_bench` im Demo-Paket.

| Panel | Zweck / `config` |
|---|---|
| `buttons` | frei benannte Knöpfe (`buttons: [{label, color, icon, shortcut, confirm, action}]`) |
| `values` | DID-Werte live: `{ecu, dids: […], refresh_ms}` |
| `timechart` | `{metric, group_by, window_s, bucket_s, ecu}` |
| `stats` | Kennzahlen `{window_s, ecu}` |
| `events` | Zeitleiste `{topics, limit}` |
| `trace` | Mini-Live-Trace `{filter, view}` |
| `ecu_status`, `log`, `note`, `run_status` | ECU-Zustand, Log-Auszug, Notiz, letzte Läufe |

Knopf-Aktionen (`action.type`): `message` (ref = Botschafts-ID), `sequence`/`test`/`suite`
(ref = ID), `uds` (`payload`, Platzhalter erlaubt), `session`, `unlock` (ref = Level), `step`
(beliebiger Schritt), `raw` (`can_id`, `payload`), `marker`, `record_start`, `record_stop`,
`report` (`report` = Report-Spezifikation).

| Route | Zweck |
|---|---|
| `GET/POST /dashboards`, `GET/PUT/DELETE /dashboards/{id}` | Verwaltung |
| `POST /dashboards/{id}/panels/{pid}/buttons/{idx}/press` | Knopf auslösen |
| `POST /actions/run` | beliebige Aktion direkt ausführen (z. B. „Testen“ im Editor) |
