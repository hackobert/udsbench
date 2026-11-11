---
id: einrichtung
title: Einrichtung & eigene Geräte
category: Grundlagen
keywords: assistent, einrichtung, wizard, gerät anlegen, steuergerät, ecu anlegen, demo ausblenden, demo entfernen, can-id, 7e0, 7e8, 18da, erste schritte
contexts: [setup, devices]
---
# Einrichtung & eigene Geräte

## Einrichtungsassistent {#assistent}

Der Assistent unter **System → Einrichtung** führt in wenigen Schritten zur ersten Antwort eines
Steuergeräts. Beim ersten Start öffnet er sich automatisch.

1. **Ziel wählen**: *Echtes Steuergerät einrichten* oder *Erst einmal ausprobieren (Demo)*.
2. **Demo-Geräte ausblenden**: Mit echter Hardware werden die Demo-Geräte ECU A, B und C nicht
   gebraucht. Nichts wird gelöscht, die Demo lässt sich jederzeit wieder einblenden.
3. **CAN-Adapter**: Treiber (z. B. PCAN), Kanal und Bitrate wählen, dann *Verbinden und prüfen*.
   udsbench hört eine Sekunde auf dem Bus mit und zeigt, ob Frames ankommen.
4. **Steuergerät**: Namen und CAN-IDs eintragen (siehe [unten](#ids)).
5. **Testen**: udsbench sendet *TesterPresent* (`3E 00`). Diese Anfrage verändert am Gerät nichts.
   Kommt keine Antwort, erklärt der Assistent die wahrscheinliche Ursache und zeigt die auf dem
   Bus gesehenen IDs, die sich direkt als Antwort-ID übernehmen lassen.
6. **Fertig**: Auf Wunsch wird die Verbindung beim nächsten Start automatisch hergestellt.

## Welche CAN-IDs? {#ids}

Die IDs stehen in der Diagnose-Dokumentation des Geräts. Die Vorlagen decken die häufigsten Fälle ab:

| Vorlage | Anfrage | Antwort | Funktional |
|---|---|---|---|
| Standard 11-Bit | `7E0` | `7E8` | `7DF` |
| 29-Bit „normal fixed“ (Ziel `10`, Tester `F1`) | `18DA10F1` | `18DAF110` | `18DB33F1` |

* **Anfrage-ID**: auf dieser ID sendet der Tester an das Gerät.
* **Antwort-ID**: auf dieser ID antwortet das Gerät.
* **Funktionale ID**: für Anfragen an alle Geräte gleichzeitig; kann leer bleiben.
* **Erweitert**: Adressierung (extended/mixed mit Adressbyte), Padding, Framelänge, CAN FD und
  Antwortzeiten P2/P2\* nur ändern, wenn die Dokumentation es verlangt. Details:
  [Adressierung & Padding](help:adressierung-padding).

## Geräte verwalten {#geraete}

Unter **System → Geräte** stehen alle Geräte:

* **Eigene Geräte**: *Neues Gerät* öffnet den Assistenten direkt beim Schritt *Steuergerät*.
  *Testen*, *Bearbeiten* und *Löschen* stehen in jeder Zeile. Eigene Geräte werden im
  Arbeitsbereich-Paket (`workspace`) gespeichert und lassen sich unter *Pakete* als YAML exportieren.
* **Demo-Geräte**: stammen aus dem eingebauten Demo-Paket. Sie werden gemeinsam mit allen
  Demo-Botschaften und -Tests über *Demo-Geräte ausblenden* entfernt und mit *einblenden* wieder
  hergestellt.
* **Geräte aus Konfig-Paketen**: werden im jeweiligen Paket gepflegt (siehe
  [Pakete & Konfiguration](help:pakete-konfiguration)).

## Keine Antwort? {#keine-antwort}

| Beobachtung im Test | Wahrscheinliche Ursache |
|---|---|
| Auf dem Bus ist nichts zu hören | Gerät aus (Zündung), CAN-High/Low vertauscht, kein Abschlusswiderstand (120 Ω), falsche Bitrate |
| Nur Fehlerframes | falsche Bitrate |
| Bus aktiv, aber nichts auf der Antwort-ID | Anfrage-/Antwort-ID oder 11/29-Bit falsch |
| Daten auf der Antwort-ID, aber keine gültige Antwort | Adressierung (Adressbyte) oder Padding passt nicht |
| Gerät lehnt ab (NRC) | Kommunikation funktioniert, nur diese Anfrage ist nicht erlaubt |

## Automatisch verbinden {#autostart}

Die im Assistenten gespeicherte Verbindung liegt in `data/setup.json` und wird beim nächsten Start
hergestellt, auch mit `udsbench run --demo`. Eine Verbindung in `config/app.yaml` hat Vorrang. Zum
Zurückstellen auf die Demo den Assistenten erneut starten und *Demo* wählen.
