---
id: aufzeichnungen
title: Aufzeichnungen & Replay
category: Beobachten
keywords: aufzeichnung, recording, replay, wiedergabe, import, export, asc, csv, candump, jsonl, zeitbasis
contexts: [recordings]
---
# Aufzeichnungen & Replay

## Aufzeichnen {#aufzeichnen}

*Aufzeichnung starten* speichert alle Frames (optional nur bestimmter Kanäle) mit Zeitstempel,
bis Sie stoppen. Die Aufzeichnung enthält zusätzlich die aktiven Paketversionen.

## Formate {#formate}

| Format | Verwendung |
|---|---|
| JSONL | natives Format, verlustfrei |
| CSV | Tabellenkalkulation, eigene Auswertungen |
| ASC | verbreitetes ASCII-Logformat für CAN-Werkzeuge |
| candump | Logformat der Linux can-utils |

Import funktioniert in allen vier Formaten; das Format wird meist automatisch erkannt.

## Replay {#replay}

| Modus | Wirkung |
|---|---|
| auf den Bus | sendet die aufgezeichneten Tx-Frames erneut; ein angeschlossenes Steuergerät antwortet live |
| in den Trace | spielt alle Frames nur in die Anzeige ein, ohne zu senden; ideal zur Analyse |

Die Zeitabstände bleiben erhalten; *Geschwindigkeit* skaliert sie (2 = doppelt so schnell).
*Wiederholungen* spielt die Aufzeichnung mehrfach ab.
