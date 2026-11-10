"""Beispiel-Plugin (wird nur geladen, wenn nach ``*.py`` ohne ``.example`` umbenannt).

Plugins erweitern udsbench um eigene Decoder, Assertions und Key-Funktionen – ohne Hersteller-Bezug
im Tool selbst.
"""


def register(registry):
    # Decoder für komplexe DID-Strukturen: ValueSpec.decoder = "temp_pair"
    registry.add_decoder("temp_pair", lambda data, spec: {"t1": data[0] - 40, "t2": data[1] - 40})

    # Eigene Assertion: expect: {custom: [{name: response_even_length}]}
    registry.add_assertion("response_even_length",
                           lambda ctx, result, params: (len(result.response or b"") % 2 == 0, "gerade Antwortlänge"))

    # Key-Funktion für Provider type: plugin, params: {function: toy_xor}
    registry.add_key_function("toy_xor", lambda seed, level, params: bytes(b ^ level for b in seed))
