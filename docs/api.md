# API & Automatisierung

Die API ist ein Erstklassen-Feature: Die Browser-UI nutzt ausschließlich dieselben Routen.
Interaktive Doku: `http://127.0.0.1:8765/docs` · OpenAPI: `/openapi.json`.

## Authentifizierung

* `Authorization: Bearer <token>` oder `X-API-Token: <token>`; WebSocket/SSE: `?token=<token>`
* Token aus `server.token` oder `UDSBENCH_TOKEN`. Ohne Token nur an Loopback gebunden; bei anderer
  Bindung ohne Token wird ein Zufallstoken erzeugt und beim Start ausgegeben.
* `GET /api/health` ist ohne Token erreichbar (`auth_required`).

## Fehlerobjekte

```json
{"error": {"code": "not_found|validation_error|conflict|not_connected|timeout|transport_error|provider_error|unauthorized",
           "message": "…", "details": [...]}}
```

HTTP-Status: 401, 404, 409 (Konflikt, nicht verbunden), 422 (Validierung), 500/502/504.

## Routen (`/api/v1`)

| Bereich | Routen |
|---|---|
| System | `GET /info`, `GET /plugins`, `GET /api/health` |
| Einrichtung & Geräte | `GET /setup`, `PUT /setup/demo` (Demo-Geräte ein/aus), `PUT /setup/connections` (beim Start verbinden), `PUT /setup/completed`, `GET /setup/bus-activity?channel=&seconds=`, `GET/POST/PUT/DELETE /devices` (eigene ECUs mit eingebettetem ISO-TP-Profil) |
| Verbindung | `GET /interfaces?detect=&interface=`, `GET/POST/DELETE /connection` (`POST …?replace=true` stellt einen verbundenen Kanal um), `POST /connection/{name}/reset`, `POST /can/send` |
| Konfiguration | `GET /config/ai-prompt`, `POST /config/ai-check`, `GET/PUT /config`, `GET /config/schema?kind=`, `POST /config/validate`, `POST /config/import`, `GET /config/export?package=&format=` |
| Pakete | `GET/POST /packages`, `GET/DELETE /packages/{id}`, `POST /packages/{id}/activate|deactivate`, `PUT /packages/active`, `POST /packages/rescan` |
| ECUs / ISO-TP | `GET /ecus`, `GET /ecus/{id}`, `POST /ecus/{id}/session`, `PUT /ecus/{id}/tester-present`, `GET /isotp/profiles`, `PUT /isotp/profiles/{name}` |
| UDS | `GET /uds/services`, `GET /uds/nrc`, `POST /uds/request`, `POST /uds/validate`, `POST /uds/decode`, `POST /uds/preview` |
| Kataloge | `GET /catalogs/dids|dtcs|routines`, `POST /dids/read|write|io-control`, `POST /dtcs/read|clear`, `POST /routines/control`, `POST /transfer`, `POST /steps/run` |
| Botschaften | `GET/POST /messages`, `GET/PUT/DELETE /messages/{id}`, `POST /messages/{id}/send|preview` |
| Sequenzen | `GET/POST /sequences`, `GET/PUT/DELETE /sequences/{id}`, `POST /sequences/{id}/run` |
| Tests | `GET/POST /tests`, `…/{id}`, `POST /tests/{id}/run`, `POST /tests/run-adhoc`, `GET/POST /testsuites`, `POST /testsuites/{id}/run`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/report?format=json|junit`, `POST /runs/{id}/cancel` |
| Security | `GET /security/providers`, `POST /security/seed|key|compute-key|unlock`, `POST /security/nrc-suite/cases|run` |
| Trace | `GET /trace?view=frames|messages&since=&…`, `DELETE /trace`, `POST /trace/bookmarks`, `GET /trace/export?format=` |
| Aufzeichnungen | `GET/POST /recordings`, `POST /recordings/stop`, `POST /recordings/import`, `GET /recordings/{id}?format=`, `GET /recordings/{id}/frames`, `DELETE /recordings/{id}`, `POST /recordings/{id}/replay`, `POST /replays/{id}/cancel` |
| Logs | `GET /logs?channel=&level=&cid=&q=&since=`, `GET /logs/stream` (SSE) |
| Statistik | `GET /stats/timeseries`, `GET /stats/summary`, `GET /events`, `POST /events/marker` |
| Reports | `GET/POST /reports`, `GET /reports/{id}?format=json\|html\|zip`, `GET /reports/{id}/attachments/{name}`, `DELETE /reports/{id}`, `GET /runs/{id}/report?format=html\|zip`, `GET /runs/{id}/export` |
| Dashboards | `GET/POST /dashboards`, `GET/PUT/DELETE /dashboards/{id}`, `POST /dashboards/{id}/panels/{pid}/buttons/{idx}/press`, `POST /actions/run` |
| Hilfe | `GET /help`, `GET /help/search?q=`, `GET /help/topics/{id}`, `GET /help/context/{ansicht}?field=`, `GET /help/tooltips` |
| Simulation | `GET /simulation`, `POST /simulation/restart`, `PUT /simulation/{ecu}/dids/{did}`, `PUT /simulation/{ecu}/dtcs/{code}`, `POST /simulation/{ecu}/reset` |

Laufende Operationen (`…/run`) liefern sofort `run_id`; mit `{"wait": true}` wird synchron bis
zum Ende gewartet und der vollständige Report zurückgegeben.

## WebSockets

* `/ws/trace` – Batches `{"type":"batch","frames":[…],"messages":[…],"dropped":n}`. Steuerung:
  `{"action":"pause"|"resume"}`, `{"action":"filter","filter":{"ids":"0x700 0x708","direction":"rx",
  "only_uds":true,"services":"0x22","data_contains":"F1 90"}}`, `{"action":"views","views":["messages"]}`.
  Filter auch als Query-Parameter.
* `/ws/events?topics=run,run.step,…` – `run`, `run.step`, `connection`, `session`, `security`,
  `uds`, `isotp`, `log`, `packages`, `recording`, `replay`, `simulation`.

## Kompletter Testlauf ohne UI

```bash
udsbench run --demo --no-browser &
curl -s -X POST localhost:8765/api/v1/packages/demo/activate
curl -s -X POST localhost:8765/api/v1/testsuites/full/run -H 'Content-Type: application/json' -d '{"wait":true}' | jq .summary
curl -s "localhost:8765/api/v1/runs/<run_id>/report?format=junit" -o report.xml
```

Python (nur Standardbibliothek): `examples/run_suite.py`; weitere curl-Beispiele: `examples/curl.sh`.
