---
id: isotp-profile
title: ISO-TP-Profile
category: Diagnose
keywords: profil, can-id, tx_id, rx_id, functional_id, 29 bit, adressbyte, live
contexts: [isotp]
---
# ISO-TP-Profile

Ein Profil beschreibt, wie mit einer ECU kommuniziert wird. Mehrere ECUs können dasselbe Profil
nutzen.

## Felder {#felder}

| Feld | Bedeutung |
|---|---|
| Kanal | Name der Verbindung |
| Tx-ID / Rx-ID | CAN-ID der Anfrage (Tester an ECU) und der Antwort |
| Funktionale ID | CAN-ID für funktionale Anfragen |
| 29-Bit-ID | Extended CAN-Identifier |
| Adressierung | normal, extended, mixed; siehe [Adressierung](help:adressierung-padding) |
| Adressbyte Tx / Rx | Byte 0 bei extended/mixed; Rx leer = nicht prüfen |
| Blocksize, STmin | eigene Flow-Control-Werte |
| Padding, Padding-Byte, DLC-Modus | Auffüllverhalten |
| CAN-FD, TX_DL | Frames bis 64 Byte |
| Timeouts | N_As, N_Ar, N_Bs, N_Cr |

## Live ändern {#live}

Änderungen gelten sofort für die laufende Sitzung, werden aber nicht in das Paket geschrieben.
Dauerhaft wird eine Änderung erst im Konfig-Paket. Die Vorschau zeigt die Wirkung auf eine
Beispielnutzlast.
