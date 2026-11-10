#!/usr/bin/env python3
"""Vorlage für einen Script-Provider (mode: stdio).

Liest den Seed als Hex von stdin und schreibt den Key als Hex auf stdout. Das Security-Level wird
als Argument übergeben (siehe `command` in der Provider-Konfiguration). Der hier gezeigte
Algorithmus ist ein frei erfundener Platzhalter – ersetzen Sie ihn lokal durch Ihre Implementierung.
"""

import sys

seed = bytes.fromhex(sys.stdin.read().strip())
level = int(sys.argv[1]) if len(sys.argv) > 1 else 1
key = bytes(((b ^ 0xA5) + level) & 0xFF for b in seed)  # Platzhalter
print(key.hex())
