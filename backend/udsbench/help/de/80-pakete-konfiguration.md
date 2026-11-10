---
id: pakete-konfiguration
title: Konfig-Pakete & Einstellungen
category: Konfiguration
keywords: paket, konfiguration, yaml, json, import, export, aktivieren, kollision, arbeitsbereich, timing, p2, tester present, log-level, vorlage, ki, spezifikation
contexts: [packages]
---
# Konfig-Pakete & Einstellungen

Alles Gerätespezifische steht in **Konfig-Paketen**, nicht im Programm. Ein Paket ist eine
YAML- oder JSON-Datei.

## Inhalt eines Pakets {#inhalt}

| Abschnitt | Inhalt |
|---|---|
| package | ID, Name, Version, Beschreibung |
| isotp_profiles | ISO-TP-Profile |
| ecus | ECU-Profile mit Sessions, Timing, Security-Levels |
| security_providers | Seed-to-Key-Provider |
| catalogs | DIDs, DTCs, Routinen |
| messages, sequences, tests, testsuites | Botschaften und Automatisierung |
| dashboards | vordefinierte Dashboards |
| simulation | Verhalten der Testdoubles |

## Aktivieren und Kollisionen {#aktivieren}

Mehrere Pakete können gleichzeitig aktiv sein. Definieren zwei Pakete dieselbe ECU-, DID- oder
Botschafts-ID, wird die Aktivierung abgelehnt und die Kollision angezeigt.

## Hochladen und Prüfen {#hochladen}

Beim Hochladen wird das Paket vollständig geprüft. Fehler nennen die genaue Stelle, z. B.
`isotp_profiles.ecu_a.padding.byte: Byte-Wert außerhalb 0x00..0xFF`. Hochgeladene Pakete liegen
im Datenverzeichnis und werden nicht ins Repository übernommen.

## Arbeitsbereich {#arbeitsbereich}

Was Sie in der Oberfläche anlegen (Botschaften, Sequenzen, Tests), landet im Paket
*Arbeitsbereich*. Es lässt sich exportieren und weitergeben.

## Vorlage für reale Steuergeräte {#vorlage}

`config/templates/real_ecu.template.yaml` enthält alle Abschnitte mit Platzhaltern. Kopieren,
ausfüllen, hochladen. Schneller geht es mit dem KI-Assistenten, der ein Paket direkt aus der
Spezifikation erstellt: [Konfiguration aus Spezifikation](help:ki-konfiguration).

## Laufzeit-Einstellungen {#laufzeit}

| Einstellung | Bedeutung |
|---|---|
| P2 / P2* | Antwortzeit-Grenzen der ECU (werden aus der 0x10-Antwort übernommen) |
| Zuschlag | Reserve für Laufzeiten im Netzwerk |
| max. ResponsePending | wie viele 0x78 akzeptiert werden |
| Validierung | strict, warn oder off |
| TesterPresent | Keep-Alive in Nicht-Default-Sessions: Intervall, unterdrückte Antwort, physikalisch/funktional |
| Log-Level | TRACE bis ERROR |
| Secrets maskieren | Seeds, Keys und Zugangsdaten in Logs verbergen |
