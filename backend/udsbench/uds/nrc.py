"""Vollständige Negative-Response-Code-Tabelle nach ISO 14229-1:2020 (Annex A.1)."""

from __future__ import annotations

NRC_TABLE: dict[int, tuple[str, str]] = {
    0x00: ("positiveResponse", "Positive Antwort (nicht als NRC verwendet)"),
    0x10: ("generalReject", "Allgemeine Ablehnung"),
    0x11: ("serviceNotSupported", "Dienst nicht unterstützt"),
    0x12: ("subFunctionNotSupported", "Subfunktion nicht unterstützt"),
    0x13: ("incorrectMessageLengthOrInvalidFormat", "Falsche Nachrichtenlänge oder ungültiges Format"),
    0x14: ("responseTooLong", "Antwort zu lang"),
    0x21: ("busyRepeatRequest", "Beschäftigt – Anfrage wiederholen"),
    0x22: ("conditionsNotCorrect", "Bedingungen nicht erfüllt"),
    0x24: ("requestSequenceError", "Falsche Anfragereihenfolge"),
    0x25: ("noResponseFromSubnetComponent", "Keine Antwort von Subnetz-Komponente"),
    0x26: ("failurePreventsExecutionOfRequestedAction", "Fehler verhindert Ausführung"),
    0x31: ("requestOutOfRange", "Anfrage außerhalb des gültigen Bereichs"),
    0x33: ("securityAccessDenied", "Sicherheitszugriff verweigert"),
    0x34: ("authenticationRequired", "Authentifizierung erforderlich"),
    0x35: ("invalidKey", "Ungültiger Schlüssel"),
    0x36: ("exceedNumberOfAttempts", "Anzahl der Versuche überschritten"),
    0x37: ("requiredTimeDelayNotExpired", "Erforderliche Wartezeit nicht abgelaufen"),
    0x38: ("secureDataTransmissionRequired", "Gesicherte Datenübertragung erforderlich"),
    0x39: ("secureDataTransmissionNotAllowed", "Gesicherte Datenübertragung nicht erlaubt"),
    0x3A: ("secureDataVerificationFailed", "Prüfung gesicherter Daten fehlgeschlagen"),
    0x50: ("certificateVerificationFailedInvalidTimePeriod", "Zertifikat: ungültiger Zeitraum"),
    0x51: ("certificateVerificationFailedInvalidSignature", "Zertifikat: ungültige Signatur"),
    0x52: ("certificateVerificationFailedInvalidChainOfTrust", "Zertifikat: ungültige Vertrauenskette"),
    0x53: ("certificateVerificationFailedInvalidType", "Zertifikat: ungültiger Typ"),
    0x54: ("certificateVerificationFailedInvalidFormat", "Zertifikat: ungültiges Format"),
    0x55: ("certificateVerificationFailedInvalidContent", "Zertifikat: ungültiger Inhalt"),
    0x56: ("certificateVerificationFailedInvalidScope", "Zertifikat: ungültiger Geltungsbereich"),
    0x57: ("certificateVerificationFailedInvalidCertificate", "Zertifikat ungültig (widerrufen)"),
    0x58: ("ownershipVerificationFailed", "Besitzprüfung fehlgeschlagen"),
    0x59: ("challengeCalculationFailed", "Challenge-Berechnung fehlgeschlagen"),
    0x5A: ("settingAccessRightsFailed", "Setzen der Zugriffsrechte fehlgeschlagen"),
    0x5B: ("sessionKeyCreationDerivationFailed", "Sitzungsschlüssel-Erzeugung fehlgeschlagen"),
    0x5C: ("configurationDataUsageFailed", "Verwendung der Konfigurationsdaten fehlgeschlagen"),
    0x5D: ("deAuthenticationFailed", "De-Authentifizierung fehlgeschlagen"),
    0x70: ("uploadDownloadNotAccepted", "Upload/Download nicht akzeptiert"),
    0x71: ("transferDataSuspended", "Datenübertragung unterbrochen"),
    0x72: ("generalProgrammingFailure", "Allgemeiner Programmierfehler"),
    0x73: ("wrongBlockSequenceCounter", "Falscher Blocksequenzzähler"),
    0x78: ("requestCorrectlyReceivedResponsePending", "Anfrage korrekt empfangen – Antwort ausstehend"),
    0x7E: ("subFunctionNotSupportedInActiveSession", "Subfunktion in aktiver Session nicht unterstützt"),
    0x7F: ("serviceNotSupportedInActiveSession", "Dienst in aktiver Session nicht unterstützt"),
    0x81: ("rpmTooHigh", "Drehzahl zu hoch"),
    0x82: ("rpmTooLow", "Drehzahl zu niedrig"),
    0x83: ("engineIsRunning", "Motor läuft"),
    0x84: ("engineIsNotRunning", "Motor läuft nicht"),
    0x85: ("engineRunTimeTooLow", "Motorlaufzeit zu kurz"),
    0x86: ("temperatureTooHigh", "Temperatur zu hoch"),
    0x87: ("temperatureTooLow", "Temperatur zu niedrig"),
    0x88: ("vehicleSpeedTooHigh", "Geschwindigkeit zu hoch"),
    0x89: ("vehicleSpeedTooLow", "Geschwindigkeit zu niedrig"),
    0x8A: ("throttlePedalTooHigh", "Fahrpedal zu hoch"),
    0x8B: ("throttlePedalTooLow", "Fahrpedal zu niedrig"),
    0x8C: ("transmissionRangeNotInNeutral", "Getriebe nicht in Neutral"),
    0x8D: ("transmissionRangeNotInGear", "Getriebe nicht in Gang"),
    0x8F: ("brakeSwitchesNotClosed", "Bremsschalter nicht geschlossen"),
    0x90: ("shifterLeverNotInPark", "Wählhebel nicht in Parkstellung"),
    0x91: ("torqueConverterClutchLocked", "Wandlerkupplung gesperrt"),
    0x92: ("voltageTooHigh", "Spannung zu hoch"),
    0x93: ("voltageTooLow", "Spannung zu niedrig"),
    0x94: ("resourceTemporarilyNotAvailable", "Ressource vorübergehend nicht verfügbar"),
}

NRC_BY_NAME: dict[str, int] = {name.lower(): code for code, (name, _) in NRC_TABLE.items()}


def nrc_name(code: int) -> str:
    if code in NRC_TABLE:
        return NRC_TABLE[code][0]
    if 0x95 <= code <= 0xEF:
        return "reservedForSpecificConditionsNotCorrect"
    if 0xF0 <= code <= 0xFE:
        return "vehicleManufacturerSpecificConditionsNotCorrect"
    return "ISOSAEReserved"


def nrc_description(code: int) -> str:
    if code in NRC_TABLE:
        return NRC_TABLE[code][1]
    if 0x95 <= code <= 0xEF:
        return "Reserviert für spezifische Bedingungen"
    if 0xF0 <= code <= 0xFE:
        return "Herstellerspezifische Bedingung nicht erfüllt"
    return "ISO/SAE reserviert"


def parse_nrc(value: int | str) -> int:
    """NRC aus Zahl, Hex-String oder Namen (z. B. "invalidKey")."""
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.lower() in NRC_BY_NAME:
        return NRC_BY_NAME[s.lower()]
    from ..core.hexutil import parse_int

    return parse_int(s)


def nrc_table_list() -> list[dict[str, object]]:
    return [
        {"code": c, "hex": f"0x{c:02X}", "name": n, "description": d}
        for c, (n, d) in sorted(NRC_TABLE.items())
    ]
