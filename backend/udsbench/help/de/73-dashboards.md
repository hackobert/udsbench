---
id: dashboards
title: Dashboards & eigene Knöpfe
category: Auswertung
keywords: dashboard, panel, knopf, button, aktion, layout, raster, widget, werte, eigene oberfläche
contexts: [dashboards]
---
# Dashboards & eigene Knöpfe

Ein Dashboard ist Ihre eigene Arbeitsfläche aus Panels in einem Raster mit 12 Spalten.

## Panel-Typen {#panels}

| Panel | Zeigt |
|---|---|
| Knöpfe | eigene, frei benannte Knöpfe für häufige Aktionen |
| Werte | DID-Werte, regelmäßig aktualisiert |
| Timechart | Zeitverlauf, siehe [Timechart](help:timechart) |
| Kennzahlen | Statistik eines Zeitfensters |
| Ereignisse | jüngste Ereignisse |
| Trace | kleiner Live-Trace mit Filter |
| ECU-Status | Session, Entsperrung, Keep-Alive |
| Log | Auszug aus einem Log-Kanal |
| Notiz | freier Text, z. B. Prüfanweisung |
| Testläufe | letzte Läufe mit Status |

## Knöpfe anlegen {#knoepfe}

Im Bearbeitungsmodus fügen Sie einem Knopf-Panel einen Knopf hinzu, benennen ihn und wählen die
Aktion:

| Aktion | Auswahl |
|---|---|
| Botschaft senden | eine vordefinierte Botschaft |
| Sequenz, Test, Suite | startet einen Lauf; der Status erscheint am Knopf |
| UDS-Anfrage | freie Hex-Nutzlast |
| Session, Entsperren | Session bzw. Security-Level |
| Schritt | beliebiger Sequenzschritt |
| Roh-Frame | CAN-ID und Daten ohne ISO-TP |
| Markierung, Aufzeichnung, Report | Zeitleiste markieren, Aufzeichnung starten/stoppen, Report erzeugen |

Optional: Farbe, Tastenkürzel und *Vor dem Auslösen nachfragen* für riskante Aktionen wie
Fehlerspeicher löschen. *Testen* führt die Aktion sofort aus, ohne zu speichern. Das Ergebnis
erscheint direkt am Knopf: Antwort, Klartext des NRC, Antwortzeit.

Schneller Weg: In *Botschaften* auf *Als Knopf auf Dashboard legen* klicken.

## Layout {#layout}

Im Bearbeitungsmodus verschieben Sie Panels per Ziehen und ändern die Größe am Rand. *Speichern*
sichert das Dashboard dauerhaft.

## Dashboards aus Konfig-Paketen {#pakete}

Pakete können Dashboards mitbringen (z. B. *Demo-Prüfstand*). Diese sind schreibgeschützt;
*Duplizieren* erzeugt eine bearbeitbare Kopie.
