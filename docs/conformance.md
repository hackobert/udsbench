# UDS-/ISO-TP-Konformität

Normbezug: ISO 14229-1 (Services, NRC), ISO 14229-2 (Timing/Session), ISO 15765-2 (ISO-TP),
ISO 15765-4 (Randbedingungen). Abweichungen sind nur über dokumentierte Konfigurationsoptionen möglich.

## ISO-TP (ISO 15765-2)

### PCI-/Längenbyte und Adressierungsmodus

| Modus | Byte 0 | PCI | UDS-Nutzdaten ab |
|---|---|---|---|
| normal | PCI | Byte 0 | Byte 1 (SF) / 2 (FF) |
| extended (N_TA) | Zieladresse `tx_address_extension` | **Byte 1** | Byte 2 (SF) / 3 (FF) |
| mixed (N_AE) | Adress-Erweiterung `tx_address_extension` | **Byte 1** | Byte 2 (SF) / 3 (FF) |

**Längensemantik:**

* **SF**: `0x0L` – `L` = Anzahl der **folgenden** Nutzdatenbytes (1–7 normal, 1–6 extended/mixed).
  CAN-FD mit CAN_DL > 8: Escape `0x00 LL`.
* **FF**: `0x1H LL` – 12-Bit-**Gesamtlänge** der UDS-Nachricht; > 4095 Byte: `0x10 0x00` + 32 Bit.
* **CF**: `0x2N` – Sequenznummer N (1…15, 0…15 umlaufend).
* **FC**: `0x3S BS STmin` – S: 0 CTS, 1 WAIT, 2 OVFLW.

Der Anwender baut diese Bytes nie selbst: Der Transport erzeugt sie automatisch, die Vorschau
(`POST /uds/preview`, UI „UDS senden“) zeigt sie mit Byte-Rollen (`ae`, `pci`, `len`, `data`, `pad`).

### Padding / DLC

| `padding.enabled` | `dlc_mode` | klassisches CAN | CAN-FD |
|---|---|---|---|
| true | fixed | jeder Frame 8 Byte, mit `padding.byte` aufgefüllt | jeder Frame `fd_tx_dl` |
| true | minimal | nur nötige Bytes | nächste gültige FD-Länge, mit `padding.byte` |
| false | (beliebig) | nur nötige Bytes | nächste gültige FD-Länge (DLC-Stufe) |

Beim Empfang werden Padding-Bytes anhand der PCI-Länge ignoriert. Beispiel „ECU erwartet volle
8-Byte-Frames mit `0xFF`“: `padding: {enabled: true, byte: 0xFF}`, `dlc_mode: fixed`.

### Weitere Punkte

BS und STmin (0x00–0x7F ms, 0xF1–0xF9 = 100–900 µs, reservierte Werte → 127 ms), FC.WAIT bis
`wft_max`, FC.OVFLW (Senden und bei `max_rx_length` Empfangen), N_As/N_Ar (Sende-Timeout), N_Bs
(Warten auf FC), N_Cr (Warten auf CF), Sequenzfehler, unerwartete SF/FF während der Segmentierung
(Abbruch/Neustart), 11/29-Bit-IDs, funktionale Adressierung (nur SF, eigene ID/Adressbyte).

## UDS-Timing (ISO 14229-2)

* P2-Timeout zählt ab vollständiger Übertragung; P2client = P2server_max + `margin_ms`.
* Nach NRC 0x78 Verlängerung auf P2*server_max + `margin_ms`, mehrfach, Limit `max_response_pending`.
* P2/P2* werden aus der 0x50-Response übernommen (`adopt_server_timing`), nach ECUReset zurückgesetzt.
* **S3**: TesterPresent (0x3E, wahlweise SPRM, physikalisch/funktional) im eingestellten Intervall,
  sobald eine Nicht-Default-Session aktiv und die ECU idle ist. Ohne Keep-Alive fällt der lokale
  Session-Zustand nach `s3_server_ms` auf DefaultSession zurück (Security wird gesperrt).
* Unterdrückte positive Antworten (SPRMIB): optional wird P2 lang auf eine NRC gewartet
  (`await_nrc_on_suppress`), der Zustandswechsel wird übernommen.

## Services

Katalog (Subfunktionen, Mindest-/Exaktlängen, SPRM-Zulässigkeit) für 0x10, 0x11, 0x14, 0x19,
0x22, 0x23, 0x24, 0x27, 0x28, 0x29, 0x2A, 0x2C, 0x2E, 0x2F, 0x31, 0x34–0x38, 0x3D, 0x3E, 0x83–0x87.
Vollständige NRC-Tabelle inkl. Bereichen (0x95–0xEF, 0xF0–0xFE). Validierungsmodi: `strict`
(Fehler blockieren), `warn`, `off` (für bewusst fehlerhafte Requests, z. B. NRC-Provokation).

## Konformitäts-Testsuite

`pytest -m conformance` (Teil von `pytest`):

| Datei | Inhalt |
|---|---|
| `test_isotp_codec.py` | PCI-Position je Modus, SF/FF/CF-Längensemantik, Escape-Formate, Padding `00/AA/FF/CC`, fixed/minimal, FD-DLC-Stufen, **Round-Trip über 48 Profilvarianten × 11 Längen**, STmin, Fehlerfälle |
| `test_isotp_transport.py` | Segmentierung beidseitig, BS → mehrere FC, STmin ms/µs eingehalten, N_Bs, N_Cr, WAIT/WFTmax, OVFLW, Sequenzfehler, unerwartete Frames, 29 Bit + extended, CAN-FD |
| `test_uds_codec.py` | Servicekatalog vollständig, NRC-Tabelle, Request-Validierung (Längen, SPRM, Subfunktionen), Dekodierung |
| `test_uds_timing.py` | 0x78 → P2*, Pending-Limit, P2-Timeout, verspätete Antworten, P2-Übernahme, SPRMIB, TesterPresent hält Session, S3-Rückfall, funktionale Mehrfachantworten, NRC-Unterdrückung funktional |
