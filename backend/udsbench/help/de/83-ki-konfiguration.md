---
id: ki-konfiguration
title: Konfiguration aus Spezifikation (KI-Assistent)
category: Konfiguration
keywords: ki, ai, prompt, spezifikation, pdf, lastenheft, hersteller, automatisch, import, chatgpt, assistent, korrektur
contexts: [packages]
---
# Konfiguration aus Spezifikation (KI-Assistent)

Steuergeräte-Spezifikationen (CAN-IDs, Adressierung, DIDs, DTCs, Routinen, Sessions, Security)
lassen sich mit einer KI in ein importierbares Konfig-Paket übersetzen. udsbench liefert dafür
einen fertigen Prompt, der genau beschreibt, wie das Paket aussehen muss.

## Ablauf {#ablauf}

1. **Prompt erzeugen**: *Pakete & Konfiguration* → *Konfiguration aus Spezifikation (KI)*.
   Optional Paket-ID und Name vorgeben, Inhalte auswählen und Hinweise ergänzen, z. B.
   „nur die Diagnose über den Fahrzeug-CAN“. Dann **Prompt kopieren**.
2. **An die KI geben**: Prompt einfügen und die Spezifikation (PDF) anhängen. Bei sehr langen
   Spezifikationen hilft es, nur die Kapitel zu Kommunikation und Diagnose mitzugeben.
3. **Antwort einfügen**: Die komplette Antwort der KI in das Feld *Antwort der KI* kopieren.
   Codeblöcke und Begleittext werden automatisch erkannt.
4. **Prüfen**: udsbench validiert das Paket wie beim normalen Import und zeigt die Zahl der ECUs,
   DIDs, DTCs und Tests sowie alle Stellen mit `TODO` oder `PRÜFEN`.
5. **Korrigieren, falls nötig**: Bei Fehlern **Korrektur-Prompt kopieren** und der KI geben. Er
   enthält das bisherige Paket und die genauen Fehlermeldungen. Die neue Antwort wieder einfügen.
6. **Importieren**: Das Paket wird gespeichert und aktiviert.

## Was der Prompt festlegt {#inhalt}

| Teil | Inhalt |
|---|---|
| Auftrag | was aus der Spezifikation entstehen soll (ISO-TP, ECUs, Security, Kataloge, Botschaften, Tests) |
| Regeln | nichts erfinden, Fundstellen als Kommentar, Unklares als `# PRÜFEN:`, Hex-Schreibweise, eindeutige IDs |
| Feldreferenz | alle erlaubten Felder mit Typ, Pflicht/Default und Bedeutung, erzeugt aus dem Schema dieser Version |
| Beispiel | ein kleines, gültiges Paket mit neutralen Werten |
| Ausgabeformat | ein YAML-Codeblock, danach „Offene Punkte“ und „Zusammenfassung“ |
| Selbstprüfung | Checkliste, die die KI vor der Ausgabe abarbeitet |

Weil die Feldreferenz aus dem installierten Schema erzeugt wird, passt der Prompt immer zur
verwendeten Version.

## Security Access {#security}

Seed-to-Key-Verfahren und Schlüssel werden **nie** von der KI nachgebaut oder eingetragen. Der
Prompt verlangt stattdessen einen Provider mit `TODO_`-Platzhaltern, z. B. für eine Bibliothek, die
Sie lokal bereitstellen. Zugangsdaten gehören als `${ENV:NAME}` in die Umgebung. Siehe
[Security Access](help:security#provider).

## Ergebnis prüfen {#pruefen}

Eine KI kann Werte falsch lesen. Prüfen Sie vor dem Einsatz an einem echten Steuergerät:

* CAN-IDs, 11/29 Bit und Adressierung gegen die Spezifikation.
* Padding und DLC-Modus (viele ECUs verlangen volle 8 Byte mit FF oder CC).
* Skalierung und Einheiten der DIDs an zwei, drei bekannten Werten.
* Alle Einträge unter „Offene Punkte“ sowie `TODO` und `PRÜFEN`.

Erst mit dem virtuellen Bus und Testdouble ausprobieren, dann am Prüfstand mit dem Live-Trace
gegenprüfen.

## Datenschutz {#datenschutz}

Spezifikationen sind oft vertraulich. Nutzen Sie nur eine KI, die für vertrauliche Dokumente Ihres
Unternehmens freigegeben ist. Erzeugte Pakete liegen lokal im Datenverzeichnis und werden nicht ins
Repository übernommen.

## Ohne Oberfläche {#cli}

```
udsbench ai-prompt --package-id projekt_x -o prompt.md
udsbench ai-check antwort.md -o projekt_x.yaml
```

`ai-check` gibt bei Fehlern direkt den Korrektur-Prompt aus. Per API: `GET /api/v1/config/ai-prompt`
und `POST /api/v1/config/ai-check`.
