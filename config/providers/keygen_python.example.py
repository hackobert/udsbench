"""Vorlage für einen Python-Provider (type: python).

Die Funktion erhält Seed, Security-Level und die Provider-Parameter aus der Konfiguration.
Zugangsdaten niemals hier ablegen – stattdessen per Parameter ``${ENV:NAME}`` übergeben.
"""


def compute_key(seed: bytes, level: int, params: dict) -> bytes:
    factor = int(params.get("factor", 3))  # frei erfundener Platzhalter-Algorithmus
    return bytes((b * factor + level) & 0xFF for b in seed)
