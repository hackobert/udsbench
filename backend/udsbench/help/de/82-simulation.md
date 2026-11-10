---
id: simulation
title: Simulation (ECU-Testdouble)
category: Konfiguration
keywords: simulation, testdouble, simuliert, ohne hardware, override, fehlerinjektion, pending, verzögerung
contexts: [connection]
---
# Simulation (ECU-Testdouble)

Das Testdouble verhält sich wie ein Steuergerät auf dem virtuellen Bus. Es wird im Abschnitt
`simulation` eines Konfig-Pakets beschrieben.

## Was es kann {#umfang}

| Bereich | Verhalten |
|---|---|
| Sessions | Wechsel, P2/P2* in der Antwort, Rückfall in die Default Session ohne Keep-Alive |
| Security Access | Seeds, Key-Prüfung über einen Provider, Fehlversuchszähler, Sperrzeit |
| DIDs | Lesen und Schreiben mit Session-, Security- und Längenprüfung |
| DTCs | Statusbytes, Snapshots, Löschen |
| Routinen | Start/Stop/Ergebnis, optional mit 0x78-Zwischenantworten |
| Speicher | Lesen/Schreiben per Adresse, Download/Upload |
| Funktional | antwortet auf funktionale Anfragen, unterdrückt dort NRCs wie 0x11 |

## Fehler gezielt erzeugen {#overrides}

Mit `overrides` reagiert das Testdouble auf passende Anfragen anders:

```yaml
overrides:
  - {match: "31 01 FF 00", respond: "7F 31 22"}
  - {match: "22 F1 ??", pending: 3, delay_ms: 200, respond: "62 F1 00 01"}
  - {match: "3E 00", respond: null, times: 2}
```

`??` steht für ein beliebiges Byte, `*` am Ende für beliebige weitere Bytes. `respond: null`
bedeutet keine Antwort (Timeout-Test).

## Zustand ändern {#zustand}

Über die API lassen sich DID-Werte und DTC-Status im laufenden Testdouble setzen, z. B. um einen
Fehler „auftreten“ zu lassen: `PUT /api/v1/simulation/ecu_a/dtcs/012345 {"status": "0x09"}`.
