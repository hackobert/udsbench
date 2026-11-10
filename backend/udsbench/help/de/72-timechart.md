---
id: timechart
title: Timechart & Statistik
category: Auswertung
keywords: timechart, diagramm, zeitachse, statistik, ereignisse, markierung, latenz, antwortzeit, buslast, kennzahlen
contexts: [timechart, dashboards]
---
# Timechart & Statistik

Die Timechart zeigt, was über die Zeit passiert: gestapelte Balken je Zeitintervall, darunter
eine Spur mit Ereignissen.

## Messgröße und Gruppierung {#messgroesse}

| Messgröße | Gruppierung | Beispiel |
|---|---|---|
| UDS | Typ | positive, negative, Timeout, unterdrückt |
| UDS | Service | ReadDataByIdentifier, SecurityAccess … |
| UDS | ECU, NRC | welche ECU, welche Ablehnungsgründe |
| Frames | Typ, Richtung, ID, ECU | Anfrage, Antwort, FF/CF/FC; Buslast je ID |
| Ereignisse | Thema, Typ | Sessions, Security, Testläufe, Fehler |

Die Intervallgröße passt sich dem Zeitfenster an und lässt sich festlegen. Ein Klick auf einen
Legendeneintrag blendet die Gruppe aus. Die Linie zeigt die mittlere Antwortzeit.

## Ereignis-Spur {#ereignisse}

Markierungen auf der Zeitachse für Session-Wechsel, Entsperren, Start und Ende von Testläufen,
Verbindungsereignisse, ISO-TP-Fehler, Warnungen und eigene Markierungen. Ein Klick zeigt die
Details. *Markierung setzen* hält einen Moment fest, etwa „Zündung an“.

## Kennzahlen {#kennzahlen}

Anzahl Anfragen, Verteilung positiv/negativ/Timeout, häufigste Services und NRCs, mittlere,
minimale und maximale Antwortzeit, Anzahl Frames.

## Gespeicherte Historie {#historie}

Ereignisse werden zusätzlich je Tag im Datenverzeichnis gespeichert. Damit funktionieren
Auswertungen und Reports auch nach einem Neustart.
