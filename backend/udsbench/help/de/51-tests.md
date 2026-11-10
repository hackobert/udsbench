---
id: tests
title: Tests & Testsuiten
category: Automatisierung
keywords: test, testsuite, assertion, erwartung, expect, datensatz, setup, teardown, report, junit, lauf, run, negativtest
contexts: [tests]
---
# Tests & Testsuiten

## Aufbau eines Tests {#aufbau}

| Teil | Zweck |
|---|---|
| preconditions | Vorbedingungen; schlägt eine fehl, endet der Test mit *Fehler* statt *fehlgeschlagen* |
| setup | Vorbereitung (z. B. Session wechseln) |
| steps | die eigentlichen Prüfschritte |
| teardown | Aufräumen; läuft immer, auch nach Fehlern |
| datasets | datengetrieben: je Datensatz ein Durchlauf |
| repeat | Wiederholungen |
| expected_result | `fail` für Negativtests |

## Assertions {#assertions}

| Prüfung | Beispiel |
|---|---|
| positive | `{positive: true}` |
| nrc | `{nrc: 0x31}`, `{nrc: invalidKey}` oder eine Liste |
| response | `{response: "62 F1 90 ?? *"}` mit `??` für ein beliebiges Byte, `*` für den Rest |
| response_prefix | `{response_prefix: "62 F1 90"}` |
| length, min_length | Antwortlänge |
| max_time_ms | Antwortzeit-Obergrenze |
| no_response | `true` erwartet keine Antwort |
| pending_max | höchstens n mal 0x78 |
| fields | Wert im dekodierten Ergebnis, z. B. `fields.session: 3` |
| expr | Ausdruck, z. B. `values['user_setting'] == 42` |
| responses_min | funktional: Mindestanzahl antwortender ECUs |

Ohne `expect` erwarten Komfortschritte (session, read_did …) eine positive Antwort; `send`
erwartet irgendeine Antwort. `expect: {}` schaltet alle Prüfungen ab.

## Status {#status}

| Status | Bedeutung |
|---|---|
| bestanden | alle Prüfungen erfüllt |
| fehlgeschlagen | mindestens eine Prüfung nicht erfüllt |
| Fehler | Ausführung nicht möglich (Vorbedingung, Verbindung, Konfiguration) |
| abgebrochen | vom Benutzer gestoppt |

## Reports {#reports}

Jeder Lauf erzeugt einen Report mit Umgebung, Paketversionen, allen Schritten, Requests,
Responses und Assertions (erwartet und tatsächlich). Export als JSON, JUnit-XML (für CI), HTML
oder ZIP mit den Traces und Logs des Laufzeitraums. Siehe [Reports](help:reports).
