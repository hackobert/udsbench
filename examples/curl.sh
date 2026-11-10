#!/usr/bin/env bash
# Beispielaufrufe der udsbench-API mit curl.  Server: `udsbench run --demo`
# Optional: export UDSBENCH_TOKEN=...   (wird als Bearer-Token gesendet)
set -euo pipefail
BASE="${UDSBENCH_URL:-http://127.0.0.1:8765}/api/v1"
AUTH=()
[ -n "${UDSBENCH_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer ${UDSBENCH_TOKEN}")
j() { curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' "$@"; echo; }

# Status und verfügbare Interfaces
j "$BASE/info"
j "$BASE/interfaces"

# Verbinden: virtueller Bus mit ECU-Testdouble (bzw. python-can: {"backend":"python-can","options":{"interface":"socketcan","channel":"can0","bitrate":500000}})
j -X POST "$BASE/connection" -d '{"name":"default","backend":"virtual","options":{"bus":"vbus0"},"simulate":true}' || true

# Paket aktivieren
j -X POST "$BASE/packages/demo/activate"

# Rohe UDS-Anfrage → dekodierte Antwort
j -X POST "$BASE/uds/request" -d '{"ecu":"ecu_a","payload":"22 F1 00"}'

# Frame-Vorschau: wie wird die Nutzlast auf den Bus gelegt (PCI, Adressbyte, Padding)?
j -X POST "$BASE/uds/preview" -d '{"ecu":"ecu_b","payload":"2E 02 00 00 2A"}'

# Session wechseln, Security-Unlock (Provider aus der Konfiguration), DID schreiben
j -X POST "$BASE/ecus/ecu_a/session" -d '{"session":"extendedDiagnosticSession"}'
j -X POST "$BASE/security/unlock" -d '{"ecu":"ecu_a","level":1}'
j -X POST "$BASE/dids/write" -d '{"ecu":"ecu_a","did":"user_setting","value":42}'
j -X POST "$BASE/dids/read" -d '{"ecu":"ecu_a","dids":["user_setting","supply_voltage"]}'

# Fehlerspeicher
j -X POST "$BASE/dtcs/read" -d '{"ecu":"ecu_a","subfunction":2,"mask":255}'

# Testsuite synchron ausführen und JUnit-Report holen
RUN=$(curl -sS "${AUTH[@]}" -H 'Content-Type: application/json' -X POST "$BASE/testsuites/full/run" -d '{"wait":true}' \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["run_id"]); print(d["status"], d["summary"], file=sys.stderr)')
curl -sS "${AUTH[@]}" "$BASE/runs/$RUN/report?format=junit" -o "report-$RUN.xml" && echo "JUnit: report-$RUN.xml"

# Security-Access-NRC-Testsuite
j -X POST "$BASE/security/nrc-suite/run" -d '{"ecu":"ecu_a","level":1,"wait":true}' | head -c 600; echo

# Aufzeichnung
j -X POST "$BASE/recordings" -d '{"name":"curl-demo"}'
j -X POST "$BASE/uds/request" -d '{"ecu":"ecu_a","payload":"3E 00"}'
j -X POST "$BASE/recordings/stop"

# Logs (Audit-Kanal) und Live-Stream (SSE, Strg+C zum Beenden)
j "$BASE/logs?channel=audit&limit=5"
# curl -N "${AUTH[@]}" "$BASE/logs/stream?channel=comm"
