# Provider-Verzeichnis (`paths.providers_dir`)

Hier legen Anwender **lokal** ihre Seed-to-Key-Implementierungen ab (Shared Libraries, Skripte,
Python-Dateien, Zusatzdateien). Dieses Verzeichnis ist – bis auf `*.example.*` und diese Datei –
**git-ignoriert**. Es werden niemals proprietäre Bibliotheken, Schlüssel oder Zugangsdaten eingecheckt.

Vorlagen:

* `keygen_script.example.py` – Script-Provider (stdin/stdout)
* `keygen_python.example.py` – Python-Provider (`compute_key(seed, level, params)`)

Die Anbindung erfolgt ausschließlich über die Konfiguration (`security_providers` im Konfig-Paket),
siehe `docs/security-providers.md`.
