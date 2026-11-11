---
id: verbindung
title: Verbindung & CAN-Adapter
category: Grundlagen
keywords: adapter, interface, python-can, socketcan, bitrate, kanal, virtuell, bus, reset, can-fd
contexts: [connection]
---
# Verbindung & CAN-Adapter

## Backend wählen {#backend}

* **Virtueller Bus**: prozessinterner Bus ohne Hardware. Alle Teilnehmer mit demselben
  *Bus-Namen* sehen sich gegenseitig. Ideal zum Kennenlernen, für Tests und CI.
* **python-can**: Zugang zu realer Hardware. Welcher Treiber verwendet wird, bestimmen
  ausschließlich die Optionen.

| Option | Beispiel | Bedeutung |
|---|---|---|
| interface | socketcan | Treibername laut python-can |
| channel | can0 | Kanal oder Gerät des Treibers |
| bitrate | 500000 | Nominal-Bitrate in Bit/s |
| fd | true | CAN-FD aktivieren |
| data_bitrate | 2000000 | Datenphasen-Bitrate bei CAN-FD |

Weitere treiberspezifische Optionen werden unverändert weitergegeben.

Beim Wechsel des Interfaces wird der übliche Kanalname vorbelegt (z. B. `can0` für socketcan,
`PCAN_USBBUS1` für pcan). **Suchen** neben dem Kanal fragt python-can nach angeschlossenen Adaptern
des gewählten Interfaces und bietet die gefundenen Kanäle zur Auswahl an.

## PCAN-Adapter {#pcan}

* **Interface** `pcan`, **Kanal** `PCAN_USBBUS1` (zweiter Adapter `PCAN_USBBUS2` usw., PCI-Karten
  `PCAN_PCIBUS1`). `can0` funktioniert mit `pcan` nicht.
* **Treiber:** Windows: Gerätetreiber von PEAK-System (enthält die PCAN-Basic-Bibliothek
  `PCANBasic.dll`). Linux: entweder PCAN-Basic für Linux, oder den im Kernel enthaltenen Treiber
  `peak_usb` mit Interface `socketcan` und Kanal `can0` verwenden. macOS: PCBUSB-Bibliothek.
* Den Adapter vorher in anderen Programmen (z. B. PCAN-View) freigeben – er kann nur von einem
  Programm gleichzeitig geöffnet werden.
* **CAN-FD:** udsbench berechnet aus *Bitrate* und *Daten-Bitrate* das Bit-Timing für den 80-MHz-Takt
  der PCAN-Hardware (Abtastpunkt 80 %, änderbar mit `sample_point` / `data_sample_point`). Eigene
  Werte (`f_clock`, `nom_brp`, `nom_tseg1` …) haben Vorrang.

## Kanalname {#kanalname}

Jede Verbindung hat einen Namen (Standard `default`). ISO-TP-Profile verweisen über `channel`
auf diesen Namen. So lassen sich mehrere Busse gleichzeitig betreiben.

## ECU-Testdouble {#testdouble}

*ECU-Testdouble starten* legt für alle ECUs der aktiven Pakete mit `simulation`-Abschnitt
simulierte Steuergeräte auf den virtuellen Bus. Siehe [Simulation](help:simulation).

## Status und Bus-Reset {#status}

Die Statuskarte zeigt gesendete und empfangene Frames, Sendefehler und den Adapterzustand
(z. B. ACTIVE, PASSIVE, BUS_OFF, sofern der Treiber ihn liefert). **Bus-Reset** schließt und
öffnet den Adapter neu, hilfreich nach Bus-Off.

## Typische Probleme {#probleme}

* *CAN-Interface konnte nicht geöffnet werden*: Die Meldung nennt Interface, Kanal und meist einen
  konkreten Hinweis. Treiber installiert? Kanalname richtig (bei PCAN siehe [oben](#pcan))? Unter
  Linux die Schnittstelle vorher aktivieren: `ip link set can0 up type can bitrate 500000`.
* *Keine Antworten*: Stimmen Bitrate, CAN-IDs und Adressierung? Im Trace prüfen, ob die Anfrage
  gesendet wird und ob Fehlerframes erscheinen.
