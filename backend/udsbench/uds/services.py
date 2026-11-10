"""UDS-Servicekatalog nach ISO 14229-1 (Requests, Subfunktionen, Mindestlängen, SPRMIB)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # "byte" | "u16" | "u24" | "u32" | "did" | "rid" | "dtc" | "hex" | "alfid" | "mask"
    description: str = ""
    optional: bool = False
    default: str | None = None


@dataclass(frozen=True)
class Service:
    sid: int
    name: str
    description: str
    has_subfunction: bool = False
    subfunctions: dict[int, str] = field(default_factory=dict)
    sprm_allowed: bool = False
    min_len: int = 1
    #: Mindestlänge je Subfunktion (Gesamtlänge inkl. SID)
    sub_min_len: dict[int, int] = field(default_factory=dict)
    #: Exakte Länge je Subfunktion, falls die Norm sie festlegt
    sub_exact_len: dict[int, int] = field(default_factory=dict)
    params: tuple[Param, ...] = ()
    #: Parameter abhängig von der Subfunktion
    sub_params: dict[int, tuple[Param, ...]] = field(default_factory=dict)
    exact_len: int | None = None

    @property
    def response_sid(self) -> int:
        return (self.sid + 0x40) & 0xFF

    def to_dict(self) -> dict[str, Any]:
        def _p(ps: tuple[Param, ...]) -> list[dict[str, Any]]:
            return [p.__dict__ for p in ps]

        return {
            "sid": self.sid,
            "sid_hex": f"0x{self.sid:02X}",
            "name": self.name,
            "description": self.description,
            "has_subfunction": self.has_subfunction,
            "sprm_allowed": self.sprm_allowed,
            "subfunctions": [
                {"value": k, "hex": f"0x{k:02X}", "name": v} for k, v in sorted(self.subfunctions.items())
            ],
            "min_len": self.min_len,
            "exact_len": self.exact_len,
            "sub_min_len": {f"0x{k:02X}": v for k, v in self.sub_min_len.items()},
            "sub_exact_len": {f"0x{k:02X}": v for k, v in self.sub_exact_len.items()},
            "params": _p(self.params),
            "sub_params": {f"0x{k:02X}": _p(v) for k, v in self.sub_params.items()},
            "response_sid": self.response_sid,
        }


_DTC_MASK = Param(
    "DTCStatusMask",
    "mask",
    "Statusmaske (Bits: TF, TFTOC, PDTC, CDTC, TNCSLC, TFSLC, TNCTOC, WIR)",
    default="FF",
)
_DTC = Param("DTCMaskRecord", "dtc", "DTC (3 Byte)")
_SNAP = Param("DTCSnapshotRecordNumber", "byte", default="FF")
_EXT = Param("DTCExtDataRecordNumber", "byte", default="FF")
_SEV = Param("DTCSeverityMask", "byte")
_MEM = Param("MemorySelection", "byte")

_SECURITY_SUBS: dict[int, str] = {}
for _lvl in range(0x01, 0x7F):
    if _lvl in (0x5F, 0x60):
        _SECURITY_SUBS[_lvl] = "ISO26021-2 values"
    elif 0x43 <= _lvl <= 0x5E:
        _SECURITY_SUBS[_lvl] = ("requestSeed" if _lvl % 2 else "sendKey") + " (ISOSAEReserved)"
    elif 0x61 <= _lvl <= 0x7E:
        _SECURITY_SUBS[_lvl] = ("requestSeed" if _lvl % 2 else "sendKey") + " (systemSupplierSpecific)"
    else:
        _SECURITY_SUBS[_lvl] = (
            f"requestSeed (Level {(_lvl + 1) // 2})" if _lvl % 2 else f"sendKey (Level {_lvl // 2})"
        )


SERVICES: dict[int, Service] = {
    s.sid: s
    for s in [
        Service(
            0x10,
            "DiagnosticSessionControl",
            "Diagnose-Session wechseln",
            True,
            {
                0x01: "defaultSession",
                0x02: "programmingSession",
                0x03: "extendedDiagnosticSession",
                0x04: "safetySystemDiagnosticSession",
            },
            sprm_allowed=True,
            min_len=2,
            exact_len=2,
        ),
        Service(
            0x11,
            "ECUReset",
            "Steuergeräte-Reset",
            True,
            {
                0x01: "hardReset",
                0x02: "keyOffOnReset",
                0x03: "softReset",
                0x04: "enableRapidPowerShutDown",
                0x05: "disableRapidPowerShutDown",
            },
            sprm_allowed=True,
            min_len=2,
            exact_len=2,
        ),
        Service(
            0x14,
            "ClearDiagnosticInformation",
            "Fehlerspeicher löschen",
            min_len=4,
            params=(
                Param("groupOfDTC", "u24", "DTC-Gruppe (FFFFFF = alle)", default="FFFFFF"),
                Param("MemorySelection", "byte", optional=True),
            ),
        ),
        Service(
            0x19,
            "ReadDTCInformation",
            "Fehlerspeicher lesen",
            True,
            {
                0x01: "reportNumberOfDTCByStatusMask",
                0x02: "reportDTCByStatusMask",
                0x03: "reportDTCSnapshotIdentification",
                0x04: "reportDTCSnapshotRecordByDTCNumber",
                0x05: "reportDTCStoredDataByRecordNumber",
                0x06: "reportDTCExtDataRecordByDTCNumber",
                0x07: "reportNumberOfDTCBySeverityMaskRecord",
                0x08: "reportDTCBySeverityMaskRecord",
                0x09: "reportSeverityInformationOfDTC",
                0x0A: "reportSupportedDTC",
                0x0B: "reportFirstTestFailedDTC",
                0x0C: "reportFirstConfirmedDTC",
                0x0D: "reportMostRecentTestFailedDTC",
                0x0E: "reportMostRecentConfirmedDTC",
                0x14: "reportDTCFaultDetectionCounter",
                0x15: "reportDTCWithPermanentStatus",
                0x16: "reportDTCExtDataRecordByRecordNumber",
                0x17: "reportUserDefMemoryDTCByStatusMask",
                0x18: "reportUserDefMemoryDTCSnapshotRecordByDTCNumber",
                0x19: "reportUserDefMemoryDTCExtDataRecordByDTCNumber",
                0x1A: "reportSupportedDTCExtDataRecord",
                0x42: "reportWWHOBDDTCByMaskRecord",
                0x55: "reportWWHOBDDTCWithPermanentStatus",
                0x56: "reportDTCInformationByDTCReadinessGroupIdentifier",
            },
            sprm_allowed=False,
            min_len=2,
            sub_exact_len={
                0x01: 3,
                0x02: 3,
                0x03: 2,
                0x04: 6,
                0x05: 3,
                0x06: 6,
                0x07: 4,
                0x08: 4,
                0x09: 5,
                0x0A: 2,
                0x0B: 2,
                0x0C: 2,
                0x0D: 2,
                0x0E: 2,
                0x14: 2,
                0x15: 2,
                0x16: 3,
                0x17: 4,
                0x18: 7,
                0x19: 7,
                0x1A: 3,
                0x42: 5,
                0x55: 3,
                0x56: 4,
            },
            sub_params={
                0x01: (_DTC_MASK,),
                0x02: (_DTC_MASK,),
                0x04: (_DTC, _SNAP),
                0x05: (Param("DTCStoredDataRecordNumber", "byte", default="FF"),),
                0x06: (_DTC, _EXT),
                0x07: (_SEV, _DTC_MASK),
                0x08: (_SEV, _DTC_MASK),
                0x09: (_DTC,),
                0x16: (_EXT,),
                0x17: (_DTC_MASK, _MEM),
                0x18: (_DTC, _SNAP, _MEM),
                0x19: (_DTC, _EXT, _MEM),
                0x1A: (_EXT,),
                0x42: (Param("FunctionalGroupIdentifier", "byte"), _DTC_MASK, _SEV),
                0x55: (Param("FunctionalGroupIdentifier", "byte"),),
                0x56: (
                    Param("FunctionalGroupIdentifier", "byte"),
                    Param("DTCReadinessGroupIdentifier", "byte"),
                ),
            },
        ),
        Service(
            0x22,
            "ReadDataByIdentifier",
            "Daten per DID lesen",
            min_len=3,
            params=(Param("dataIdentifier", "did", "Ein oder mehrere DIDs (je 2 Byte)"),),
        ),
        Service(
            0x23,
            "ReadMemoryByAddress",
            "Speicher lesen",
            min_len=4,
            params=(
                Param("addressAndLengthFormatIdentifier", "alfid", default="44"),
                Param("memoryAddress", "hex"),
                Param("memorySize", "hex"),
            ),
        ),
        Service(
            0x24,
            "ReadScalingDataByIdentifier",
            "Skalierungsdaten lesen",
            min_len=3,
            exact_len=3,
            params=(Param("dataIdentifier", "did"),),
        ),
        Service(
            0x27,
            "SecurityAccess",
            "Sicherheitszugriff (Seed/Key)",
            True,
            _SECURITY_SUBS,
            sprm_allowed=True,
            min_len=2,
            params=(Param("securityAccessData / securityKey", "hex", optional=True),),
        ),
        Service(
            0x28,
            "CommunicationControl",
            "Kommunikation steuern",
            True,
            {
                0x00: "enableRxAndTx",
                0x01: "enableRxAndDisableTx",
                0x02: "disableRxAndEnableTx",
                0x03: "disableRxAndTx",
                0x04: "enableRxAndDisableTxWithEnhancedAddressInformation",
                0x05: "enableRxAndTxWithEnhancedAddressInformation",
            },
            sprm_allowed=True,
            min_len=3,
            sub_exact_len={0x00: 3, 0x01: 3, 0x02: 3, 0x03: 3, 0x04: 5, 0x05: 5},
            params=(Param("communicationType", "byte", "01 normal, 02 NM, 03 beide", default="01"),),
            sub_params={
                0x04: (
                    Param("communicationType", "byte", default="01"),
                    Param("nodeIdentificationNumber", "u16"),
                ),
                0x05: (
                    Param("communicationType", "byte", default="01"),
                    Param("nodeIdentificationNumber", "u16"),
                ),
            },
        ),
        Service(
            0x29,
            "Authentication",
            "Authentifizierung (PKI)",
            True,
            {
                0x00: "deAuthenticate",
                0x01: "verifyCertificateUnidirectional",
                0x02: "verifyCertificateBidirectional",
                0x03: "proofOfOwnership",
                0x04: "transmitCertificate",
                0x05: "requestChallengeForAuthentication",
                0x06: "verifyProofOfOwnershipUnidirectional",
                0x07: "verifyProofOfOwnershipBidirectional",
                0x08: "authenticationConfiguration",
            },
            sprm_allowed=True,
            min_len=2,
        ),
        Service(
            0x2A,
            "ReadDataByPeriodicIdentifier",
            "Periodische Daten",
            min_len=2,
            params=(
                Param("transmissionMode", "byte", "01 slow, 02 medium, 03 fast, 04 stop", default="01"),
                Param("periodicDataIdentifier", "hex", optional=True),
            ),
        ),
        Service(
            0x2C,
            "DynamicallyDefineDataIdentifier",
            "Dynamische DIDs definieren",
            True,
            {
                0x01: "defineByIdentifier",
                0x02: "defineByMemoryAddress",
                0x03: "clearDynamicallyDefinedDataIdentifier",
            },
            sprm_allowed=True,
            min_len=2,
        ),
        Service(
            0x2E,
            "WriteDataByIdentifier",
            "Daten per DID schreiben",
            min_len=4,
            params=(Param("dataIdentifier", "did"), Param("dataRecord", "hex")),
        ),
        Service(
            0x2F,
            "InputOutputControlByIdentifier",
            "Ein-/Ausgänge steuern",
            min_len=4,
            params=(
                Param("dataIdentifier", "did"),
                Param(
                    "inputOutputControlParameter",
                    "byte",
                    "00 returnControlToECU, 01 resetToDefault, 02 freezeCurrentState, 03 shortTermAdjustment",
                    default="00",
                ),
                Param("controlState / controlEnableMask", "hex", optional=True),
            ),
        ),
        Service(
            0x31,
            "RoutineControl",
            "Routine steuern",
            True,
            {0x01: "startRoutine", 0x02: "stopRoutine", 0x03: "requestRoutineResults"},
            sprm_allowed=True,
            min_len=4,
            params=(
                Param("routineIdentifier", "rid"),
                Param("routineControlOptionRecord", "hex", optional=True),
            ),
        ),
        Service(
            0x34,
            "RequestDownload",
            "Download anfordern",
            min_len=5,
            params=(
                Param("dataFormatIdentifier", "byte", default="00"),
                Param("addressAndLengthFormatIdentifier", "alfid", default="44"),
                Param("memoryAddress", "hex"),
                Param("memorySize", "hex"),
            ),
        ),
        Service(
            0x35,
            "RequestUpload",
            "Upload anfordern",
            min_len=5,
            params=(
                Param("dataFormatIdentifier", "byte", default="00"),
                Param("addressAndLengthFormatIdentifier", "alfid", default="44"),
                Param("memoryAddress", "hex"),
                Param("memorySize", "hex"),
            ),
        ),
        Service(
            0x36,
            "TransferData",
            "Daten übertragen",
            min_len=2,
            params=(
                Param("blockSequenceCounter", "byte", default="01"),
                Param("transferRequestParameterRecord", "hex", optional=True),
            ),
        ),
        Service(
            0x37,
            "RequestTransferExit",
            "Übertragung beenden",
            min_len=1,
            params=(Param("transferRequestParameterRecord", "hex", optional=True),),
        ),
        Service(
            0x38,
            "RequestFileTransfer",
            "Dateiübertragung",
            min_len=5,
            params=(
                Param(
                    "modeOfOperation", "byte", "01 Add, 02 Delete, 03 Replace, 04 Read, 05 ReadDir, 06 Resume"
                ),
                Param("filePathAndNameLength", "u16"),
                Param("filePathAndName", "hex"),
            ),
        ),
        Service(
            0x3D,
            "WriteMemoryByAddress",
            "Speicher schreiben",
            min_len=5,
            params=(
                Param("addressAndLengthFormatIdentifier", "alfid", default="44"),
                Param("memoryAddress", "hex"),
                Param("memorySize", "hex"),
                Param("dataRecord", "hex"),
            ),
        ),
        Service(
            0x3E,
            "TesterPresent",
            "Tester anwesend (Keep-Alive)",
            True,
            {0x00: "zeroSubFunction"},
            sprm_allowed=True,
            min_len=2,
            exact_len=2,
        ),
        Service(
            0x83,
            "AccessTimingParameter",
            "Timing-Parameter",
            True,
            {
                0x01: "readExtendedTimingParameterSet",
                0x02: "setTimingParametersToDefaultValues",
                0x03: "readCurrentlyActiveTimingParameters",
                0x04: "setTimingParametersToGivenValues",
            },
            sprm_allowed=True,
            min_len=2,
        ),
        Service(
            0x84,
            "SecuredDataTransmission",
            "Gesicherte Datenübertragung",
            min_len=2,
            params=(Param("securityDataRequestRecord", "hex"),),
        ),
        Service(
            0x85,
            "ControlDTCSetting",
            "DTC-Speicherung steuern",
            True,
            {0x01: "on", 0x02: "off"},
            sprm_allowed=True,
            min_len=2,
            params=(Param("DTCSettingControlOptionRecord", "hex", optional=True),),
        ),
        Service(
            0x86,
            "ResponseOnEvent",
            "Antwort bei Ereignis",
            True,
            {
                0x00: "stopResponseOnEvent",
                0x01: "onDTCStatusChange",
                0x02: "onTimerInterrupt",
                0x03: "onChangeOfDataIdentifier",
                0x04: "reportActivatedEvents",
                0x05: "startResponseOnEvent",
                0x06: "clearResponseOnEvent",
                0x07: "onComparisonOfValues",
                0x08: "reportMostRecentDtcOnStatusChange",
                0x09: "reportDTCRecordInformationOnDtcStatusChange",
            },
            sprm_allowed=True,
            min_len=3,
            params=(
                Param("eventWindowTime", "byte", default="02"),
                Param("eventTypeRecord / serviceToRespondToRecord", "hex", optional=True),
            ),
        ),
        Service(
            0x87,
            "LinkControl",
            "Link-Steuerung (Baudrate)",
            True,
            {
                0x01: "verifyModeTransitionWithFixedParameter",
                0x02: "verifyModeTransitionWithSpecificParameter",
                0x03: "transitionMode",
            },
            sprm_allowed=True,
            min_len=2,
            sub_exact_len={0x01: 3, 0x02: 5, 0x03: 2},
            sub_params={
                0x01: (Param("linkControlModeIdentifier", "byte"),),
                0x02: (Param("linkRecord", "u24"),),
            },
        ),
    ]
}

SERVICE_BY_RESPONSE: dict[int, Service] = {s.response_sid: s for s in SERVICES.values()}

DTC_STATUS_BITS = [
    "testFailed",
    "testFailedThisOperationCycle",
    "pendingDTC",
    "confirmedDTC",
    "testNotCompletedSinceLastClear",
    "testFailedSinceLastClear",
    "testNotCompletedThisOperationCycle",
    "warningIndicatorRequested",
]

SESSION_NAMES = {
    0x01: "defaultSession",
    0x02: "programmingSession",
    0x03: "extendedDiagnosticSession",
    0x04: "safetySystemDiagnosticSession",
}


def get_service(sid: int) -> Service | None:
    return SERVICES.get(sid)


def service_name(sid: int) -> str:
    s = SERVICES.get(sid)
    if s:
        return s.name
    if 0xBA <= sid <= 0xBE:
        return "systemSupplierSpecific"
    if 0xA0 <= sid <= 0xB9:
        return "vehicleManufacturerSpecific"
    return f"Service 0x{sid:02X}"


def subfunction_name(sid: int, sub: int) -> str | None:
    s = SERVICES.get(sid)
    if not s or not s.has_subfunction:
        return None
    return s.subfunctions.get(sub & (0x3F if sid == 0x86 else 0x7F))


def decode_dtc_status(status: int) -> dict[str, bool]:
    return {name: bool(status & (1 << i)) for i, name in enumerate(DTC_STATUS_BITS)}
