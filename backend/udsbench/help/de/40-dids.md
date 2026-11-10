---
id: dids
title: DIDs & Ein-/Ausgabe
category: Diagnose
keywords: did, data identifier, lesen, schreiben, 0x22, 0x2e, 0x2f, io control, skalierung, einheit, enum, bitfeld
contexts: [dids]
---
# DIDs & Ein-/Ausgabe

Data Identifier (DIDs) sind 16-Bit-Nummern für Messwerte und Parameter.

## Katalog {#katalog}

Der DID-Katalog stammt aus den aktiven Konfig-Paketen und beschreibt Typ, Länge, Skalierung und
Einheit. Damit wird aus den Bytes `31 38` der Wert 12,6 V.

| Typ | Darstellung |
|---|---|
| uint / int | Zahl; Wert = Rohwert × scale + offset |
| ascii / utf8 | Text |
| bcd | Ziffernfolge (`12 34` wird zu 1234) |
| enum | Zahl mit Namen (1 = standby) |
| bitfield | einzelne Bits oder Bitgruppen |
| float32/64, bool, hex | wie benannt |

## Lesen (0x22) {#lesen}

Wählen Sie einen oder mehrere DIDs. Typische Ablehnungen: 0x31 (DID unbekannt oder in dieser
Session nicht lesbar), 0x33 (Security Access erforderlich).

## Schreiben (0x2E) {#schreiben}

Die Eingabe passt sich dem Typ an: Auswahlliste für enum, Häkchen für bool, Einzelfelder für
Bitfelder, Zahl mit Einheit für Messwerte. Bereichsgrenzen (min/max) werden vor dem Senden
geprüft. Viele ECUs erlauben Schreiben nur in der Extended Session und nach Security Access.

## Ein-/Ausgänge steuern (0x2F) {#io}

| Parameter | Bedeutung |
|---|---|
| 00 returnControlToECU | Steuerung zurück an die ECU |
| 01 resetToDefault | auf Standardwert setzen |
| 02 freezeCurrentState | aktuellen Zustand einfrieren |
| 03 shortTermAdjustment | vorübergehend auf den angegebenen Wert setzen |

Geben Sie die Steuerung nach einem Test mit 00 zurück.
