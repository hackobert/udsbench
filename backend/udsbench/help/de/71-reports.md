---
id: reports
title: Reports
category: Auswertung
keywords: report, bericht, export, zeitbereich, html, zip, json, junit, anhang, trace, logs, prüfbericht
contexts: [reports, tests]
---
# Reports

## Testlauf exportieren {#testlauf}

| Format | Inhalt |
|---|---|
| JSON | vollständige Daten des Laufs, maschinenlesbar |
| JUnit-XML | für CI-Systeme (Testergebnisse je Testfall) |
| HTML | eigenständige, druckbare Datei mit allen Schritten und Assertions |
| ZIP | JSON, JUnit, HTML, die CAN-Traces des Laufzeitraums (ASC, CSV, JSONL), Logs und Ereignisse |

## Report über einen Zeitbereich {#zeitbereich}

Unter *Reports* erstellen Sie einen Bericht für einen frei gewählten Zeitraum, z. B. einen
Prüfstandslauf von 13:00 bis 13:30.

| Feld | Bedeutung |
|---|---|
| Titel, Autor, Notizen | erscheinen im Kopf des Reports |
| Von / Bis | Zeitraum; Schnellwahl für die letzten Minuten |
| ECU | optional nur eine ECU auswerten |
| Inhalte | Statistik, Ereignisse, Testläufe, UDS-Trace, CAN-Traces, Logs, Aufzeichnungen |
| Trace-Formate | Anhänge als ASC, CSV, candump oder JSONL |

Der Report enthält Kennzahlen, Diagramme (UDS-Antworten nach Typ und Service, Frames nach Typ),
die NRC-Statistik, Testläufe, die Ereignis-Zeitleiste und den rekonstruierten UDS-Trace. Rohe
Traces und Logs hängen als Dateien an. CAN-Frames stammen aus dem Live-Puffer und werden für
ältere Zeiträume aus gespeicherten Aufzeichnungen ergänzt. Wer lange Zeiträume vollständig
dokumentieren will, startet vorher eine Aufzeichnung.

Abrufen: *Ansehen* (HTML), *ZIP herunterladen* oder einzelne Anhänge.

## Aus Trace oder Timechart {#auswahl}

Markieren Sie im Trace oder in der Timechart einen Bereich und wählen Sie *Report aus Auswahl*.
Ein Dashboard-Knopf kann ebenfalls einen Report erzeugen, z. B. „letzte 15 Minuten“.
