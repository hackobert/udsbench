---
id: dbc
title: DBC & Signale
category: Beobachten
keywords: dbc, can-datenbank, signale, botschaft, message, signal, dekodieren, multiplexer, j1939, kanal, cantools
contexts: [dbc, trace]
---
# DBC & Signale

Unter **Beobachten → DBC & Signale** werden CAN-Datenbanken im DBC-Format geladen und **je Kanal**
zugeordnet. Frames eines Kanals werden mit dessen DBC-Dateien dekodiert:

* im **Trace** steht in der Spalte *Interpretation* z. B. `EngineData: EngineSpeed=1500 rpm, Mode=active`,
* unter **Signale live** erscheint je Botschaft der zuletzt empfangene Stand mit Zyklus, Anzahl und Alter.

Diagnose-Frames der eingerichteten Geräte (ISO-TP) werden weiterhin als UDS interpretiert.

## DBC hochladen {#hochladen}

1. Unter *DBC-Dateien* eine oder mehrere `.dbc`-Dateien wählen.
2. Optional gleich einem Kanal zuordnen (*Zuordnen zu*).
3. *Hochladen*. Die Datei wird geprüft; fehlerhafte DBCs werden mit Grund abgelehnt.

Die Dateien liegen in `data/dbc/` und bleiben nach einem Neustart erhalten. UTF-8 und
Windows-1252 (Umlaute in Kommentaren) werden erkannt. *Inhalt* zeigt Botschaften und Signale mit
Bitlage, Faktor/Offset, Wertebereich und Wertetabellen.

## Pro Kanal einstellen {#kanaele}

Unter *Kanäle & DBC-Zuordnung* steht jeder bekannte Kanal (verbundene, aus Geräten und gespeicherten
Verbindungen). Je Kanal lassen sich beliebig viele DBC-Dateien aktivieren. Ein noch nicht
verbundener Kanal kann mit *Kanal hinzufügen* vorab konfiguriert werden.

Definieren zwei aktive DBCs eines Kanals dieselbe CAN-ID, gilt die zuerst aktivierte. Der Konflikt
wird angezeigt.

## Botschaft senden {#senden}

*Botschaft senden* kodiert eine Botschaft aus Signalwerten (physikalische Werte oder Namen aus der
Wertetabelle) und sendet sie auf dem gewählten Kanal. Leere Felder erhalten den Startwert aus der
DBC. Bei **Multiplexern** werden nur die Signale des gewählten Zweigs verwendet; nicht passende
Signale sind ausgegraut. *Nur kodieren* zeigt die Bytes ohne zu senden.

## API {#api}

| Aufgabe | Aufruf |
|---|---|
| Übersicht | `GET /api/v1/dbc` |
| Hochladen | `POST /api/v1/dbc` mit `{"filename": "x.dbc", "content": "…", "channels": ["default"]}` |
| Zuordnen | `PUT /api/v1/dbc/channels/{kanal}` mit `{"files": ["x"]}` |
| Live-Werte | `GET /api/v1/dbc/live?channel=default` |
| Kodieren/Senden | `POST /api/v1/dbc/encode` mit `{"channel": "default", "message": "EngineData", "signals": {"EngineSpeed": 1500}, "send": true}` |
