---
id: fehlerbehebung
title: Fehlerbehebung
category: Grundlagen
keywords: problem, fehler, timeout, keine antwort, nicht verbunden, token, 401, kollision, validierung, hängt
contexts: [home, connection, uds]
---
# Fehlerbehebung

Häufige Meldungen, ihre Ursache und was Sie tun können. Die Fehlermeldungen in der Oberfläche verlinken hierher.

| Meldung | Ursache und Lösung |
|---|---|
| Kanal ist nicht verbunden | Unter *Verbindung* verbinden; der Kanalname im ISO-TP-Profil muss zur Verbindung passen. |
| Timeout: keine Antwort innerhalb P2 | ECU antwortet nicht: CAN-IDs, Adressierung, Padding und Bitrate prüfen. Im Trace sehen, ob die Anfrage gesendet wird. |
| Timeout innerhalb P2* | ECU meldete 0x78 und antwortete dann nicht mehr. P2* im ECU-Profil erhöhen. |
| Zu viele ResponsePending | Grenze *max. ResponsePending* erhöhen, wenn die ECU legitim lange rechnet. |
| Request-Validierung fehlgeschlagen | Länge oder Subfunktion passt nicht zur Norm. Für Absicht *warn* oder *off* wählen. |
| N_Bs-Timeout | Kein Flow Control auf den First Frame. Rx-ID oder Adressbyte falsch, oder die ECU erwartet aufgefüllte Frames. |
| Sequenzfehler im Trace | Consecutive Frames in falscher Reihenfolge oder verloren; Buslast und STmin prüfen. |
| API-Token fehlt oder ist ungültig | Token über *Token eingeben* setzen; bei Skripten `Authorization: Bearer …`. |
| Namenskollision zwischen aktiven Paketen | Zwei Pakete definieren dieselbe ID. Eines deaktivieren oder umbenennen. |
| Security-Provider nicht gefunden | Provider-ID im Security-Level stimmt nicht mit `security_providers` überein. |
| Key abgelehnt (0x35) | Falscher Provider oder Parameter; mit *manuell* Seed und Key vergleichen. |

## Glossar {#glossar}

| Begriff | Erklärung |
|---|---|
| UDS | Unified Diagnostic Services, ISO 14229 |
| ISO-TP | Transportprotokoll für Nachrichten über 8 Byte, ISO 15765-2 |
| SID | Service Identifier, erstes Byte einer Anfrage |
| PCI | Protocol Control Information: Frame-Typ und Länge |
| SF / FF / CF / FC | Single, First, Consecutive Frame, Flow Control |
| P2 / P2* | maximale Antwortzeit normal / nach 0x78 |
| S3 | Zeit, nach der die ECU ohne Keep-Alive in die Default Session zurückfällt |
| SPRM | Bit zur Unterdrückung der positiven Antwort |
| DID / RID / DTC | Data Identifier, Routine Identifier, Diagnostic Trouble Code |
| NRC | Negative Response Code |
| Padding | Auffüllbytes bis zur Framelänge |
| DLC | Data Length Code, Anzahl Datenbytes eines CAN-Frames |
