---
id: uds-senden
title: UDS senden
category: Diagnose
keywords: request, anfrage, service, subfunktion, sprm, suppress, vorschau, frame-vorschau, raw, funktional, physikalisch, validierung
contexts: [uds]
---
# UDS senden

## Dienst und Subfunktion {#dienst}

Wählen Sie den Dienst nach ISO 14229-1. Hat er Subfunktionen, erscheint die passende Liste.
**SPRM** (Bit 7 der Subfunktion) unterdrückt die positive Antwort; negative Antworten kommen
trotzdem. Das Häkchen erscheint nur bei Diensten, die das erlauben (z. B. 0x10 und 0x3E, nicht
0x19).

## Parameter {#parameter}

Wo möglich, wählen Sie Werte aus Katalogen, z. B. einen DID per Name. Im freien Modus geben Sie
die Nutzlast als Hex ein: `22 F1 90`, `22F190` und `0x22,0xF1,0x90` sind gleichwertig.

## Byte- und Frame-Vorschau {#vorschau}

Die obere Zeile zeigt die **UDS-Nutzlast**. Darunter zeigt die **Frame-Vorschau**, was
tatsächlich auf den Bus geht:

| Kennzeichnung | Bedeutung |
|---|---|
| Adressbyte | nur bei extended/mixed Adressierung: Byte 0 |
| PCI | Frame-Typ und bei Single Frames die Länge |
| Länge | zusätzliche Längenbytes (First Frame, CAN-FD) |
| Daten | UDS-Nutzdaten |
| Padding | Auffüllbytes bis zur Framelänge |

So sehen Sie sofort, welches Byte die Länge trägt und wie aufgefüllt wird. Nichts davon muss von
Hand gebaut werden. Details: [Adressierung & Padding](help:adressierung-padding).

## Validierung {#validierung}

Vor dem Senden prüft udsbench Länge, Subfunktion und SPRM gegen die Norm. Im Modus *strict*
blockieren Fehler das Senden. Für bewusst fehlerhafte Anfragen, etwa NRC-Tests, wählen Sie
*warn* oder *off*.

## Physikalisch oder funktional {#funktional}

*Physikalisch* geht an eine ECU. *Funktional* geht über die funktionale ID an alle ECUs derselben
Gruppe; alle Antworten werden gesammelt. Funktionale Anfragen müssen in einen Single Frame passen.

## Antwort lesen {#antwort}

* **Positiv**: SID + 0x40 mit dekodierten Feldern (Session und P2-Zeiten, DID-Werte mit Einheit,
  DTC-Listen).
* **Negativ**: `7F <SID> <NRC>` mit Klartext, z. B. 0x31 requestOutOfRange.
  Siehe [NRC-Referenz](help:nrc-referenz).
* **Antwortzeit** wird ab Ende der Übertragung gemessen. Zwischenantworten 0x78
  (ResponsePending) werden gezählt.

## Raw-Frame-Modus {#raw}

Sendet bis zu 8 Bytes (CAN-FD: 64) exakt wie eingegeben, ohne ISO-TP. Nur für Spezialfälle; der
normale Weg erzeugt PCI und Padding automatisch.
