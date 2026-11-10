---
id: botschaften-sequenzen
title: Botschaften & Sequenzen
category: Automatisierung
keywords: botschaft, message, vorlage, platzhalter, variable, sequenz, makro, schritt, seed, key, bedingung, schleife, ausdruck
contexts: [messages, sequences]
---
# Botschaften & Sequenzen

## Vordefinierte Botschaften {#botschaften}

Eine Botschaft ist eine benannte UDS-Anfrage mit Ziel-ECU, Nutzlast und optional erwarteter
Antwort. Platzhalter machen sie wiederverwendbar:

```yaml
- id: read_did_param
  ecu: ecu_a
  payload: "22 ${u16(did)}"
  vars: {did: 0xF101}
```

Botschaften aus Konfig-Paketen sind schreibgeschützt. Eigene Botschaften landen im Paket
*Arbeitsbereich*. Mit *Als Knopf auf Dashboard legen* wird daraus ein Dashboard-Knopf.

## Sequenzen {#sequenzen}

Eine Sequenz ist eine geordnete Liste von Schritten. Jeder Schritt hat genau eine Aktion:

| Aktion | Zweck |
|---|---|
| send | Botschaft oder Nutzlast senden |
| session, reset | Session wechseln, ECU zurücksetzen |
| request_seed, compute_key, send_key, unlock | Security Access in Einzelschritten oder komplett |
| read_did, write_did, io_control | DIDs typgerecht lesen, schreiben, steuern |
| read_dtc, clear_dtc, routine, transfer | Fehlerspeicher, Routinen, Datenübertragung |
| wait, set, log, assert | warten, Variable setzen, protokollieren, prüfen |
| if, repeat, sequence | Bedingung, Schleife, Unter-Sequenz |
| raw | Roh-Frame ohne ISO-TP |

Beispiel Session, Security Access, Schreiben:

```yaml
steps:
  - {session: 0x03}
  - {request_seed: 0x01}
  - {compute_key: {level: 0x01}}
  - {send: {payload: "27 02 ${key}"}, expect: {positive: true}}
  - {write_did: {did: user_setting, value: 42}}
```

## Werte übernehmen {#werte}

* `save: {name: "data[1:]"}` speichert einen Teil der Antwort als Variable.
* `request_seed` legt `seed` ab, `compute_key` legt `key` ab, `read_did` füllt `values`.
* In Vorlagen werden `${…}` ausgewertet; in `set` ein Wert mit vorangestelltem `=`.

## Ausdrücke {#ausdruecke}

Verfügbar sind Variablen, `response`, `data` (Antwort ohne SID), `nrc`, `positive`,
`elapsed_ms`, `ecu.tx_id` und Funktionen wie `u8`, `u16`, `u32`, `be`, `le`, `concat`, `invert`,
`bxor`, `crc16`, `crc32`, `len`, `ascii`. Die Auswertung ist abgesichert: kein Dateizugriff,
keine Importe.

## Ausführen {#ausfuehren}

*Ausführen* startet einen Lauf mit Schritt-für-Schritt-Protokoll. Der Lauf erscheint auch unter
*Tests* und kann als Report exportiert werden.
