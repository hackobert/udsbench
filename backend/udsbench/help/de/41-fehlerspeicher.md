---
id: fehlerspeicher
title: Fehlerspeicher (DTC)
category: Diagnose
keywords: dtc, fehler, fehlerspeicher, 0x19, 0x14, statusmaske, status, snapshot, löschen, confirmed, pending
contexts: [dtcs]
---
# Fehlerspeicher (DTC)

## Lesen (0x19) {#lesen}

| Subfunktion | Liefert |
|---|---|
| 01 reportNumberOfDTCByStatusMask | Anzahl der DTCs, deren Status zur Maske passt |
| 02 reportDTCByStatusMask | DTC-Liste mit Statusbyte |
| 04 reportDTCSnapshotRecordByDTCNumber | Umgebungsdaten zum Fehlerzeitpunkt |
| 06 reportDTCExtDataRecordByDTCNumber | erweiterte Daten (z. B. Zähler) |
| 0A reportSupportedDTC | alle unterstützten DTCs |

Die **Statusmaske** filtert nach Statusbits. FF zeigt alles, 08 nur bestätigte Fehler, 04 nur
anstehende.

## Statusbits {#statusbits}

| Bit | Name | Bedeutung |
|---|---|---|
| 0 | testFailed | letzter Test fehlgeschlagen |
| 1 | testFailedThisOperationCycle | in diesem Zyklus fehlgeschlagen |
| 2 | pendingDTC | anstehend, noch nicht bestätigt |
| 3 | confirmedDTC | bestätigt und gespeichert |
| 4 | testNotCompletedSinceLastClear | seit dem Löschen nicht vollständig getestet |
| 5 | testFailedSinceLastClear | seit dem Löschen mindestens einmal fehlgeschlagen |
| 6 | testNotCompletedThisOperationCycle | in diesem Zyklus noch nicht getestet |
| 7 | warningIndicatorRequested | Warnlampe angefordert |

Die Darstellung neben der Hexnummer (z. B. P0123-45) ist nur eine Lesehilfe. Name und
Beschreibung stammen aus dem DTC-Katalog des Konfig-Pakets.

## Löschen (0x14) {#loeschen}

FFFFFF löscht alle DTCs, eine konkrete Nummer nur diesen Eintrag. Manche ECUs erlauben das nur
in bestimmten Sessions.
