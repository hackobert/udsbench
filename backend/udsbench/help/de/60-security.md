---
id: security
title: Security Access
category: Diagnose
keywords: security, 0x27, seed, key, unlock, entsperren, provider, level, sperre, negativtest, nrc-suite
contexts: [security]
---
# Security Access

Geschützte Funktionen (Schreiben, Programmieren, Routinen) erfordern meist einen Security Access
nach ISO 14229-1 Dienst 0x27.

## Ablauf {#ablauf}

1. **Seed anfordern**: `27 <Level>` (ungerade Subfunktion, z. B. 01). Die ECU antwortet mit
   einem Zufallswert. Ein Seed aus lauter Nullen bedeutet: bereits entsperrt.
2. **Key berechnen**: Der konfigurierte *Provider* berechnet aus Seed und Level den Key.
3. **Key senden**: `27 <Level+1> <Key>`. Positive Antwort heißt: entsperrt.

Ein Sessionwechsel oder ECU-Reset sperrt wieder. Viele ECUs erlauben Security Access nicht in
der Default Session; im ECU-Profil kann dafür eine Session hinterlegt werden, in die *Entsperren*
vorher wechselt.

## Provider {#provider}

udsbench enthält keine herstellerspezifischen Verfahren. Der Key wird von einem austauschbaren
Provider berechnet, der im Konfig-Paket beschrieben ist:

| Typ | Verwendung |
|---|---|
| demo | offen dokumentierter Spielzeug-Algorithmus, nur für Demo und Tests |
| native | eigene Shared Library (.dll/.so/.dylib); Funktionsname und Signatur aus der Konfiguration |
| script | externes Programm, Seed per stdin oder Datei |
| python | Python-Datei mit `compute_key(seed, level, params)` |
| plugin | über ein Plugin registrierte Funktion |

Zugangsdaten gehören nie in Dateien: Parameter der Form `${ENV:NAME}` werden aus
Umgebungsvariablen gelesen. Jeder Versuch steht im Audit-Log; Seeds und Keys werden in Logs
maskiert.

## Manuell oder automatisch {#modi}

* **Manuell**: Seed anfordern, Key mit beliebigem Provider berechnen, Key prüfen oder ändern,
  senden. Gut zur Fehlersuche.
* **Entsperren**: alle Schritte auf einmal.

## Negative-Response-Testsuite {#nrc-suite}

Provoziert gezielt Ablehnungen und vergleicht erwarteten mit tatsächlichem NRC:

| Fall | erwartet |
|---|---|
| ungültiger Key | 0x35 invalidKey |
| Key zu lang | 0x13 |
| nicht unterstützter Level | 0x12 |
| Key ohne vorherigen Seed | 0x24 requestSequenceError |
| ungültiger Zusatzparameter | 0x31 |
| Default Session | 0x7F, 0x22, 0x33 oder 0x7E |
| Dienst nicht unterstützt | 0x11 |
| gültiger Key (Referenz) | positiv |
| zu viele Fehlversuche | 0x36 exceedNumberOfAttempts |
| Wartezeit läuft | 0x37 requiredTimeDelayNotExpired |

**Achtung:** Die letzten beiden Fälle sperren die ECU für die eingestellte Zeit. Abweichendes
Verhalten einer realen ECU wird im ECU-Profil unter `security_nrc_cases` hinterlegt.
