---
id: adressierung-padding
title: Adressierung, PCI & Padding
category: Diagnose
keywords: pci, länge, single frame, first frame, consecutive, flow control, extended, mixed, normal, padding, dlc, can-fd, stmin, blocksize
contexts: [isotp, uds]
---
# Adressierung, PCI & Padding

## Wo steht die Länge? {#pci}

| Adressierung | Byte 0 | Byte 1 | Nutzdaten ab |
|---|---|---|---|
| normal | PCI | Daten | Byte 1 |
| extended | Zieladresse (N_TA) | PCI | Byte 2 |
| mixed | Adresserweiterung (N_AE) | PCI | Byte 2 |

Beispiel: ReadDataByIdentifier F1 90, extended Adressierung mit Zieladresse 2B, Padding FF:

```
2B 03 22 F1 90 FF FF FF
Byte 0: Zieladresse
Byte 1: PCI, Single Frame mit 3 folgenden Nutzdatenbytes
Byte 2-4: Nutzdaten
Byte 5-7: Padding
```

## Längensemantik {#laenge}

* **Single Frame**: unteres Nibble = Anzahl der folgenden Nutzdatenbytes.
* **First Frame**: 12 Bit = Gesamtlänge der Nachricht (`10 14` = 20 Byte).
* **Consecutive Frame**: `2N`, N = Sequenznummer 1 bis 15, danach 0 bis 15.
* **Flow Control**: `30 BS STmin` weiter senden, `31` warten, `32` Überlauf.

## Padding {#padding}

| Einstellung | Wirkung |
|---|---|
| Padding an, DLC fest | jeder Frame hat volle Länge (8 Byte), aufgefüllt mit dem Padding-Byte |
| Padding an, DLC minimal | nur nötige Bytes (CAN-FD: nächste gültige Länge) |
| Padding aus | nur nötige Bytes |

Viele Steuergeräte verlangen voll aufgefüllte 8-Byte-Frames mit einem bestimmten Wert, oft FF
oder CC. Das stellen Sie im ISO-TP-Profil ein; der Transport erledigt den Rest. Beim Empfang
werden Padding-Bytes anhand der PCI-Länge ignoriert.

## Blocksize und STmin {#bs-stmin}

Beim Empfangen langer Nachrichten sendet udsbench Flow Control mit Ihrer Blocksize (0 = alle
Frames am Stück) und STmin (Mindestabstand). STmin-Werte: 00 bis 7F = 0 bis 127 ms,
F1 bis F9 = 100 bis 900 µs. Beim Senden hält udsbench die Werte der ECU ein.

## Timeouts {#timeouts}

N_As und N_Ar (Senden), N_Bs (Warten auf Flow Control), N_Cr (Warten auf den nächsten
Consecutive Frame); Standard jeweils 1000 ms.
