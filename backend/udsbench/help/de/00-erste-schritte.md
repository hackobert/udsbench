---
id: erste-schritte
title: Erste Schritte
category: Grundlagen
keywords: start, schnellstart, demo, einstieg, ohne hardware, virtuell
contexts: [home, connection]
---
# Erste Schritte

udsbench ist ein lokales Werkzeug zum Beobachten, Senden und automatisierten Testen von
UDS-Diagnose (ISO 14229) über CAN (ISO-TP, ISO 15765-2). Die Oberfläche im Browser ist ein reiner
Client der lokalen API: Alles, was Sie hier anklicken, lässt sich auch per Skript ausführen.

Am einfachsten ist der **Einrichtungsassistent** (*System → Einrichtung*): Er führt durch Adapter,
Steuergerät und einen ersten Test, oder startet die Demo. Siehe [Einrichtung](help:einrichtung).

## In fünf Minuten zur ersten Antwort {#fuenf-minuten}

1. **Verbinden**: Öffnen Sie *Verbindung*, wählen Sie *Virtueller Bus* und aktivieren Sie
   *ECU-Testdouble starten*. Damit laufen drei simulierte Steuergeräte ohne Hardware.
   Mit `udsbench run --demo` ist das bereits erledigt.
2. **Live-Trace ansehen**: Im *Trace* erscheinen alle CAN-Frames in Echtzeit, farblich nach
   Bedeutung markiert.
3. **Anfrage senden**: Unter *UDS senden* wählen Sie den Dienst *ReadDataByIdentifier*, die ECU
   `ecu_a` und den DID `demo_identifier`. Die Vorschau zeigt Byte für Byte, was gesendet wird.
   Mit **Strg+Enter** senden.
4. **Antwort lesen**: Die Antwort erscheint roh und interpretiert.
5. **Test ausführen**: Unter *Tests* die Suite *Smoke-Test* starten und den Report ansehen.

## Begriffe {#begriffe}

| Begriff | Bedeutung |
|---|---|
| ECU | Steuergeräte-Profil aus der Konfiguration: Name, CAN-IDs, ISO-TP-Profil, Sessions, Security |
| Konfig-Paket | YAML/JSON-Datei mit allem Gerätespezifischen (ECUs, Kataloge, Botschaften, Tests) |
| Testdouble | simuliertes Steuergerät auf dem virtuellen Bus |
| Session | Diagnose-Sitzung (Default, Programming, Extended), Wechsel mit Dienst 0x10 |
| NRC | Negative Response Code: Grund, warum eine ECU eine Anfrage ablehnt |

## Hilfe nutzen {#hilfe-nutzen}

* **F1** oder das **?**-Symbol in der Kopfzeile öffnet die Hilfe zur aktuellen Ansicht.
* Das **ⓘ** neben Eingabefeldern erklärt das Feld und verlinkt zum passenden Abschnitt.
* Die Suche durchsucht alle Themen, Dienste und NRCs.
* **Shift+?** zeigt alle Tastenkürzel.
