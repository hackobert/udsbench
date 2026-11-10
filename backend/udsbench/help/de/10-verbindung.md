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

* *CAN-Interface konnte nicht geöffnet werden*: Treiber installiert? Kanalname richtig? Unter
  Linux die Schnittstelle vorher aktivieren: `ip link set can0 up type can bitrate 500000`.
* *Keine Antworten*: Stimmen Bitrate, CAN-IDs und Adressierung? Im Trace prüfen, ob die Anfrage
  gesendet wird und ob Fehlerframes erscheinen.
