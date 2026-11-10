---
id: trace
title: Live-Trace
category: Beobachten
keywords: trace, frames, filter, pause, lesezeichen, export, farben, nachrichten, asc, csv, candump
contexts: [trace]
---
# Live-Trace

Der Trace zeigt jeden CAN-Frame, den udsbench sendet oder empfängt: Zeitstempel, ID, DLC, Daten,
ASCII und Klartext-Interpretation.

## Zwei Sichten {#sichten}

* **Frames**: jeder CAN-Frame einzeln, auch Flow Control und Consecutive Frames.
* **Nachrichten**: mehrteilige ISO-TP-Nachrichten werden zu einer Zeile zusammengesetzt.

## Farben {#farben}

| Farbe | Bedeutung |
|---|---|
| Blau | UDS-Anfrage (Tester an ECU) |
| Grün | positive Antwort (SID + 0x40) |
| Rot | negative Antwort (0x7F mit NRC) |
| Violett | First Frame, Beginn einer segmentierten Nachricht |
| Türkis | Consecutive Frame |
| Ocker | Flow Control |
| Grau | Frames ohne konfigurierte ECU |

Interpretiert werden nur Frames auf CAN-IDs, die in einem aktiven ISO-TP-Profil vorkommen.

## Filtern und Suchen {#filter}

Filter wirken bereits im Server, bei hoher Buslast kommen nur die gewünschten Frames an:
**ID** (mehrere mit Leerzeichen, z. B. `0x700 0x708`), **Daten enthält** (`F1 90`),
**Richtung**, **Service** (`0x22`) und **nur UDS**.

## Pause, Lesezeichen, Export {#pause}

* **Leertaste** pausiert die Anzeige, wenn kein Eingabefeld aktiv ist. Im Hintergrund wird
  weiter gepuffert.
* **Lesezeichen** markieren eine Zeile mit Notiz.
* **Export** speichert den Puffer als CSV, ASC, candump-Log oder JSONL.
* *verworfen: n* nennt, wie viele Frames die Anzeige bei Überlast übersprungen hat. Im Puffer
  und in Aufzeichnungen sind sie trotzdem enthalten.

## Zeitbereich als Report {#report}

Markieren Sie einen Bereich und wählen Sie *Report aus Auswahl*. Siehe [Reports](help:reports).
