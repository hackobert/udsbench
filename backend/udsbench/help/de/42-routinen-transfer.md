---
id: routinen-transfer
title: Routinen & Datenübertragung
category: Diagnose
keywords: routine, 0x31, start, stop, ergebnis, download, upload, 0x34, 0x35, 0x36, 0x37, transfer, blocksequenzzähler, flash, speicher
contexts: [routines]
---
# Routinen & Datenübertragung

## RoutineControl (0x31) {#routinen}

| Aktion | Subfunktion | Zweck |
|---|---|---|
| Start | 01 | Routine starten, optional mit Parametern |
| Stop | 02 | laufende Routine beenden |
| Ergebnis | 03 | Ergebnis abfragen |

Parameter und Ergebnisfelder werden typgerecht nach dem Routinen-Katalog kodiert und dekodiert.
Länger laufende Routinen antworten oft zuerst mit 0x78 (ResponsePending); udsbench wartet dann
automatisch länger (P2*). Stop oder Ergebnis ohne vorherigen Start liefert meist 0x24.

## Download und Upload (0x34 bis 0x37) {#transfer}

Der geführte Ablauf erledigt alle Schritte:

1. **RequestDownload (0x34)** oder **RequestUpload (0x35)** mit Adresse und Größe. Die ECU
   antwortet mit der maximalen Blocklänge.
2. **TransferData (0x36)** in Blöcken mit Blocksequenzzähler 01, 02 … FF, 00 …
3. **RequestTransferExit (0x37)**.

| Feld | Bedeutung |
|---|---|
| Adresse, Größe | Zielbereich im Speicher |
| ALFID | Längen von Adresse und Größe in Byte (44 = je 4 Byte) |
| Datenformat | Kompression/Verschlüsselung laut ECU (00 = keine) |
| Blocklänge | überschreibt den Wert der ECU (optional) |

Häufige Ablehnungen: 0x33 (Security Access fehlt), 0x70 (Download nicht akzeptiert), 0x73
(falscher Blocksequenzzähler), 0x72 (Programmierfehler).
