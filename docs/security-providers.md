# Security Access & Seed-to-Key-Provider

udsbench enthält **keine** proprietären Seed-to-Key-Verfahren und **keine** Schlüssel. Es stellt nur
die generische Schnittstelle bereit:

```python
compute_key(seed: bytes, security_level: int, params: dict) -> bytes
```

Provider werden im Konfig-Paket unter `security_providers` definiert und je Security-Level einer
ECU zugeordnet (`ecus[].security_levels[].provider`, optionale `params` überschreiben die
Provider-Parameter). Parameterwerte der Form `${ENV:NAME}` werden aus Umgebungsvariablen gelesen –
so gelangen Zugangsdaten nie in Dateien oder Logs. Relative Pfade beziehen sich auf
`paths.providers_dir` (Default `config/providers`, git-ignoriert).

| Typ | Zweck | Wichtige Parameter |
|---|---|---|
| `demo` | Spielzeug-Algorithmus (nur Demo/Tests) | `mask` (Hex), `key_length` |
| `script` | externes Programm | `command` (Liste/String mit `{seed}`, `{level}`, `{seed_file}`, `{key_file}`, `{python}`, `{param_X}`), `mode` `stdio`/`file`, `timeout_s`, `cwd`, `env` |
| `native` | Shared Library (`.dll/.so/.dylib`) per ctypes | `library`, `function`, `calling_convention`, `args`, `return`, `key_buffer_size`, `key_length`, `init` |
| `python` | Python-Datei mit `compute_key` | `file`, `function` |
| `plugin` | registrierte Plugin-Funktion | `function` |

## Demo-Algorithmus (offen dokumentiert, kein reales Verfahren)

```
x    = seed[i] XOR mask[i mod len(mask)] XOR (level * 0x11 mod 256)
k[i] = (rotl8(x, 1) + i) mod 256
```

Testvektor: Seed `01 02 03 04`, Level 1, Maske `5A A5` → Key `94 6E 92 64`.

## Native Library – Signatur aus der Konfiguration

Die Reihenfolge von `args` entspricht der C-Signatur. Bausteine:

| Baustein | C-Typ | Wert |
|---|---|---|
| `seed_ptr` | `const uint8_t*` | Seed |
| `{seed_len: uint32}` | Integer | Seed-Länge |
| `{level: uint32}` | Integer | Security-Level (Seed-Subfunktion) |
| `key_ptr` | `uint8_t*` | Ausgabepuffer (`key_buffer_size`) |
| `{key_buffer_size: uint32}` | Integer | Puffergröße |
| `key_len_ptr` | `uint32_t*` | tatsächliche Key-Länge (out) |
| `{key_len_in: uint32}` | Integer | feste Key-Länge (`key_length`) |
| `{const_int: N}` / `{const_str: "…"}` | `int` / `const char*` | Konstante (`path: true` → Pfad auflösen, `${ENV:…}` erlaubt) |
| `{param: name}` | `int`/`const char*` | Wert aus `params` |

`return: {type: int, success: 0}` prüft den Rückgabewert; `init` führt vorab Initialisierungs-
funktionen aus (einmal pro geladener Bibliothek). Ein vollständiges Beispiel steht in
`config/templates/real_ecu.template.yaml`, ein Test mit einer zur Laufzeit kompilierten
Bibliothek in `backend/tests/test_security.py`.

## Abläufe

* **Manuell**: `POST /security/seed` → `POST /security/compute-key` → `POST /security/key`
* **Automatisch**: `POST /security/unlock` (optional vorher Sessionwechsel gemäß `session`)
* **Schritte**: `request_seed`, `compute_key`, `send_key`, `unlock`
* Jeder Versuch wird im **Audit-Log** protokolliert; Seeds/Keys werden in Logs maskiert
  (`logging.mask_secrets`).

## Negative-Response-Testsuite

`POST /security/nrc-suite/run {"ecu": "…", "level": 1}` erzeugt datengetriebene Provokationstests
und wertet „erwarteter vs. tatsächlicher NRC“ aus:

| Fall | erwartet |
|---|---|
| ungültiger Key | 0x35 invalidKey |
| falsches Format / Länge | 0x13 |
| nicht unterstützte Subfunktion | 0x12 |
| Key ohne Seed | 0x24 requestSequenceError |
| Wert außerhalb Bereich (securityAccessDataRecord) | 0x31 |
| Zugriff in DefaultSession | 0x7F / 0x22 / 0x33 / 0x7E |
| Dienst nicht unterstützt (ISO-reservierte SID) | 0x11 |
| positiver Referenzfall | positive Response |
| Fehlversuchssperre | 0x36 exceedNumberOfAttempts |
| Zeitsperre | 0x37 requiredTimeDelayNotExpired |

Optionen (`options`): `session`, `max_attempts`, `key_length`, `unsupported_level`,
`unsupported_request`, `out_of_range_request`. ECU-spezifische Abweichungen (anderer NRC,
deaktivierte Fälle, eigene Schritte, zusätzliche Fälle) über `ecus[].security_nrc_cases`.
**Achtung:** Die Fälle „Fehlversuchssperre“/„Zeitsperre“ sperren die ECU für die konfigurierte Zeit.
