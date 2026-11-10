# Architektur

```
Browser-UI (Vanilla TS, reiner API-Client)          Externe Automatisierung (CI, Skripte, Prüfstand)
        │  REST /api/v1  ·  WS /ws/trace, /ws/events          │ REST/OpenAPI
        ▼                                                      ▼
┌──────────────────────────── udsbench-Server (FastAPI, ein Prozess) ────────────────────────────┐
│ api/        routes.py (REST, OpenAPI, Auth) · ws.py (Trace, Events) · deps.py (Token)            │
│ testrunner/ Test-Runner, Assertions, Reports (JSON/JUnit)                                       │
│ messages/   Sequenz-Engine, Botschaften, sichere Ausdrücke (${…})                               │
│ security/   Provider-Schnittstelle (demo/script/native/python/plugin), Unlock, NRC-Testsuite    │
│ core/       Platform (Komposition), diag (ECU-Laufzeit: Session, S3/TesterPresent, Security),   │
│             trace (Klassifizierung, Ringpuffer), events, Korrelations-IDs                        │
│ uds/        Servicekatalog, NRC-Tabelle, Validierung, Dekodierung, Client (P2/P2*/0x78/SPRMIB)  │
│ isotp/      Codec (reine Funktionen), Transport (async, FC/BS/STmin/Timeouts), Monitor (passiv) │
│ can/        Frame, Adapter (virtual, python-can), Kanal, Verbindungsmanager (Multi-Kanal)       │
│ config/     Schemas (Pydantic), Loader, Paketverwaltung (Merge, Kollisionen), Arbeitsbereich    │
│ catalogs/   DID/DTC/Routinen (typgerechte Kodierung)                                            │
│ logs/       Strukturiertes Logging (JSONL je Kanal), Recorder/Replay, Trace-Formate             │
│ simulation/ ECU-Testdouble auf dem virtuellen Bus                                               │
│ plugins/    Registry für Decoder, Assertions, Key-Funktionen                                     │
└──────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                               │
                              CAN-Hardware (python-can) / virtueller Bus
```

## Schichten

1. **CAN** (`can/`): `CanAdapter` mit `open/close/send/status/reset`. Empfang per Callback im
   Eventloop (python-can liest in einem Thread und übergibt per `call_soon_threadsafe`). `CanChannel`
   verteilt Rx- und Tx-Frames an Listener (ISO-TP-Transports, Trace, Recorder).
2. **ISO-TP** (`isotp/`): `codec.py` kodiert/dekodiert Frames ohne I/O – Grundlage für Senden,
   Vorschau und Round-Trip-Tests. `transport.py` implementiert den Protokollablauf; `monitor.py`
   rekonstruiert Nachrichten passiv für den Nachrichten-Trace (auch bei Replay).
3. **UDS** (`uds/`): `UdsClient.request()` mit P2/P2*-Handling ab Ende der Übertragung, beliebig
   vielen 0x78 (Limit), Zuordnung über SID-Echo, SPRMIB, funktionalem Sammeln mehrerer Antworten.
4. **Anwendung**: `core/diag.EcuRuntime` hält pro ECU Transport, Client, Session-/Security-Zustand
   und den TesterPresent-Task; Engine, Runner, Security nutzen ausschließlich diese Schicht.
5. **API**: alles ist über `/api/v1` erreichbar; die UI nutzt dieselben Routen.

## Nebenläufigkeit

Ein asyncio-Eventloop: Empfang (Callbacks), Transport-Timer, TesterPresent-Tasks, Testläufe
(Tasks, seriell über einen Runner-Lock), Replays und API-Anfragen laufen nebenläufig. Requests pro
ECU sind über einen Lock serialisiert (TesterPresent wartet, bis die ECU idle ist). Der Trace wird
pro WebSocket-Client gepuffert und gebündelt (`trace.ws_batch_ms`), bei Überlast verworfen und
gemeldet.

## Korrelation

Jeder API-Request (`req_…`), Unlock (`unlock_…`) und Testlauf (`run_…`) setzt eine Korrelations-ID
(contextvars). Sie erscheint in allen Log-Einträgen (`cid`), in Trace-Frames (`cid`) und im Report
(`run_id`) und ist über `GET /logs?cid=…` filterbar.
