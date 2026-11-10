# Konfiguration & Konfig-Pakete

Herstellerspezifika sind **Daten, nicht Code**. Sie stehen ausschließlich in Konfig-Paketen
(YAML/JSON). Das Repository enthält nur neutrale Beispiele (`*.example.yaml`) und Vorlagen.

* JSON-Schema: `udsbench schema package` bzw. `GET /api/v1/config/schema?kind=package`
* Validierung: `udsbench validate <datei…>` bzw. `POST /api/v1/config/validate`
* Paketverzeichnisse: `paths.package_dirs` (Default `config/packages`) + Datenverzeichnis
  `data/packages` (per UI/API hochgeladene Pakete, git-ignoriert)
* Aktive Pakete werden in `data/state.json` gemerkt; beim allerersten Start sind die
  Beispielpakete aktiv. Namenskollisionen zwischen aktiven Paketen (ECU, Profil, DID, Botschaft …)
  werden beim Aktivieren erkannt und abgewiesen.

## App-Konfiguration (`config/app.yaml`)

Siehe `config/app.example.yaml`. Wichtig: `server.host` (Default `127.0.0.1`), `server.token`
(besser `UDSBENCH_TOKEN`), `logging` (Level `TRACE…ERROR`, Verzeichnis, Rotation, Maskierung),
`timing` und `tester_present` (Defaults für alle ECUs), `connections` (automatisch verbinden),
`active_packages`.

## Paketaufbau

```yaml
schema_version: 1
package: {id: my_pkg, name: …, version: 1.0.0, description: …}
isotp_profiles: {<name>: {...}}         # ISO-TP-Profile (s. u.)
security_providers: [{id, type, params}] # Seed→Key-Provider (docs/security-providers.md)
ecus: [...]                              # ECU-/Ziel-Profile
catalogs: {dids: [...], dtcs: [...], routines: [...]}
messages: [...]                          # vordefinierte Botschaften
sequences: [...]                         # Sequenzen/Makros
tests: [...]                             # Testfälle
testsuites: [...]                        # Testsuiten
simulation: {ecus: [...]}                # ECU-Testdouble (optional)
```

### ISO-TP-Profil

| Feld | Default | Bedeutung |
|---|---|---|
| `channel` | `default` | CAN-Kanal |
| `tx_id` / `rx_id` | – | Request-/Response-ID |
| `functional_id` | – | funktionale Request-ID |
| `extended_id` | `false` | 29-Bit-IDs |
| `addressing` | `normal` | `normal` / `extended` / `mixed` |
| `tx_address_extension` / `rx_address_extension` / `functional_address_extension` | – | Byte 0 bei extended/mixed (Rx: Filter, `null` = nicht prüfen) |
| `block_size`, `st_min` | 0, 0 | eigene Flow-Control-Parameter (STmin-Rohwert, `0xF1–0xF9` = µs) |
| `st_min_tx_override` | – | STmin der ECU beim Senden überschreiben |
| `wft_max` | 10 | max. FC.WAIT |
| `padding.enabled`, `padding.byte` | `true`, `0xCC` | Auffüllen und Füllbyte |
| `dlc_mode` | `fixed` | `fixed` (volle Länge) / `minimal` |
| `can_fd`, `fd_tx_dl`, `bitrate_switch` | `false`, 64, `true` | CAN-FD |
| `max_rx_length` | 4095 | größere eingehende Nachrichten → FC.OVFLW |
| `timeouts` | 1000 ms | `n_as`, `n_ar`, `n_bs`, `n_cr` |

### ECU

```yaml
- id: ecu_a
  isotp: profile_name          # oder Inline-Profil
  functional_group: group_1    # ECUs mit gleicher Gruppe beantworten funktionale Anfragen
  sessions: [{id: 0x01, name: defaultSession}, {id: 0x40, name: vendorSession}]
  timing: {p2_ms: 50, p2_star_ms: 5000, margin_ms: 100, max_response_pending: 20,
           adopt_server_timing: true, await_nrc_on_suppress: true, validation: strict}
  tester_present: {enabled: true, interval_ms: 2000, suppress_response: true,
                   addressing: physical, s3_server_ms: 5000}
  security_levels: [{level: 0x01, provider: provider_id, params: {...}, session: 0x03}]
  security_nrc_cases: [{id: conditions_not_correct, name: …, expected_nrc: 0x22}]  # optional
  vars: {...}                  # in Ausdrücken als ecu.<name>
```

### Kataloge

DID: `id`, `name`, `type` (`uint int float32 float64 ascii utf8 hex bcd enum bitfield bool`),
`length`, `byteorder`, `scale`, `offset`, `unit`, `enum`, `bits`, `min`, `max`, `access`,
`io_control`, `decoder` (Plugin). DTC: `code` (3 Byte), `name`, `description`. Routine: `id`,
`name`, `start_params`, `stop_params`, `result_fields` (je Feld wie ein DID-Wert).

## Botschaften

```yaml
- id: read_did_param
  ecu: ecu_a
  payload: "22 ${u16(did)}"     # Hex mit Platzhaltern
  vars: {did: 0xF101}            # Defaults
  functional: false
  expect: {positive: true}       # optional
```

## Schritte (Sequenzen und Tests)

Jeder Schritt hat **genau eine Aktion** und optional `name`, `ecu`, `expect`, `save`
(Variable → Ausdruck), `continue_on_failure`, `retries`, `timeout_ms`.

| Aktion | Beispiel |
|---|---|
| `send` | `{send: {message: read_identifier}}` · `{send: {payload: "27 02 ${key}"}}` · `functional: true` |
| `raw` | `{raw: {id: 0x700, data: "02 3E 00 CC CC CC CC CC"}}` (umgeht ISO-TP) |
| `session` | `{session: 0x03}` oder Name |
| `reset` | `{reset: 0x01}` |
| `request_seed` / `send_key` / `compute_key` | Seed in `seed`, Key in `key` |
| `unlock` | `{unlock: 0x01}` – kompletter Ablauf über den konfigurierten Provider |
| `read_did` / `write_did` / `io_control` | per Name oder ID, typgerecht kodiert; Werte landen in `values` |
| `read_dtc` / `clear_dtc` | `{read_dtc: {subfunction: 0x02, mask: 0xFF}}` → `dtcs`, `dtc_count` |
| `routine` | `{routine: {id: demo_self_test, action: start, params: {...}}}` |
| `transfer` | `{transfer: {direction: download, address: 0x1000, data: "…"}}` (0x34→0x36…→0x37, Blocksequenzzähler) |
| `wait`, `set`, `log`, `assert` | `{wait: 100}` · `{set: {n: "=n+1"}}` · `{log: "…${n}"}` · `{assert: "n == 3"}` |
| `if` / `repeat` / `sequence` | Bedingungen, Schleifen (`count`, `until`), Unter-Sequenzen mit `vars` |
| `tester_present` | Keep-Alive ein/aus |

Ohne `expect` gilt: Komfortaktionen erwarten eine positive Antwort; `send` erwartet irgendeine
Antwort (bei SPRMIB keine Prüfung). `expect: {}` schaltet alle Prüfungen ab.

### Assertions (`expect`)

`positive`, `nrc` (Zahl, Name oder Liste), `response` (Muster mit `??` und `*`), `response_prefix`,
`length`, `min_length`, `max_time_ms`, `min_time_ms`, `no_response`, `pending_max`, `responses_min`
(funktional), `fields` (Pfad im dekodierten Ergebnis, z. B. `fields.session`), `expr` (Ausdruck),
`custom` (Assertion-Plugins).

### Ausdrücke und Platzhalter

`${…}` in Vorlagen, `=…` in `set`/`vars`, sowie `expr`/`assert`/`save`/`if`. Verfügbar: Variablen,
`response`, `data` (ohne SID), `nrc`, `positive`, `elapsed_ms`, `pending`, `decoded`, `seed`, `key`,
`values`, `dtcs`, `ecu.tx_id` … Funktionen: `u8 u16 u24 u32 u16le u32le be le bytes concat bxor
invert repeat zeros len int hex ascii crc16 crc32 sum8 contains startswith min max abs round`.
Die Auswertung ist sandboxed (AST-Whitelist, keine Attribute mit `_`, keine Importe).

## Tests und Suiten

```yaml
tests:
  - id: write_value
    ecu: ecu_a
    tags: [smoke]
    vars: {…}
    datasets: [{value: 1}, {value: 500}]   # datengetrieben
    preconditions: [...]                    # Fehler → Status "error"
    setup: [...]
    steps: [...]
    teardown: [...]                         # läuft immer
    repeat: 1
    abort_on_failure: true
    timeout_s: 30
    expected_result: pass                   # "fail" für Negativtests
testsuites:
  - id: smoke
    tests: [write_value]
    tags: [smoke]                           # zusätzlich alle Tests mit diesen Tags
    setup: [...]
    teardown: [...]
    stop_on_failure: false
```

## ECU-Testdouble (`simulation.ecus`)

Siehe `simulation/models.py` bzw. das Demo-Paket: `sessions`, `p2_server_max_ms`,
`p2_star_server_max_ms`, `s3_server_ms`, `response_delay_ms`, `services`, `service_sessions`,
`dids`, `dtcs`, `routines` (`pending`), `security` (`seed_length`, `provider`, `max_attempts`,
`lockout_ms`, `static_seed`), `memory_size`, `max_block_length` und `overrides` zur
Fehlerinjektion (`match`, `respond`, `pending`, `delay_ms`, `times`).
