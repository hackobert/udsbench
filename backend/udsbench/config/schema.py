"""Schemas für App-Konfiguration und Konfig-Pakete."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..catalogs.models import Catalogs
from ..core.types import HexByte
from ..dashboards.models import Dashboard
from ..isotp.profile import IsoTpProfile
from ..messages.models import MessageDef, SequenceDef
from ..simulation.models import SimulationConfig
from ..testrunner.models import SuiteDef, TestDef

# --------------------------------------------------------------------------------------------
# UDS-Timing / Sessions / Security
# --------------------------------------------------------------------------------------------


class UdsTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p2_ms: float = Field(50, description="P2server_max (Default bis zur Übernahme aus 0x50)")
    p2_star_ms: float = Field(5000, description="P2*server_max")
    margin_ms: float = Field(100, description="Zuschlag für Netzwerklaufzeit (P2client = P2 + margin)")
    max_response_pending: int = Field(20, description="Max. Anzahl 0x78 bevor abgebrochen wird")
    adopt_server_timing: bool = Field(True, description="P2/P2* aus der 0x10-Response übernehmen")
    await_nrc_on_suppress: bool = Field(True, description="Bei SPRMIB trotzdem P2 auf mögliche NRC warten")
    validation: Literal["strict", "warn", "off"] = "strict"


class TesterPresentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_ms: int = Field(2000, ge=100)
    suppress_response: bool = True
    addressing: Literal["physical", "functional"] = "physical"
    s3_server_ms: int = Field(5000, description="S3server – Rückfall in DefaultSession ohne Keep-Alive")


class SessionDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: HexByte
    name: str


DEFAULT_SESSIONS = [
    SessionDef(id=0x01, name="defaultSession"),
    SessionDef(id=0x02, name="programmingSession"),
    SessionDef(id=0x03, name="extendedDiagnosticSession"),
    SessionDef(id=0x04, name="safetySystemDiagnosticSession"),
]


class SecurityProviderDef(BaseModel):
    """Seed-to-Key-Provider. Alle Details (Bibliothek, Signatur, Parameter) kommen aus der Konfig."""

    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["demo", "script", "native", "python", "plugin"]
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class SecurityLevelDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(..., description="Seed-Subfunktion (ungerade, 0x01..0x7D)")
    name: str = ""
    provider: str | None = Field(None, description="ID eines security_providers-Eintrags")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Provider-Parameter (überschreiben Provider-Defaults)"
    )
    session: HexByte | None = Field(None, description="Vor dem Unlock in diese Session wechseln")

    @model_validator(mode="after")
    def _odd(self) -> SecurityLevelDef:
        if self.level % 2 == 0 or not 0x01 <= self.level <= 0x7D:
            raise ValueError("Security-Level muss die ungerade requestSeed-Subfunktion sein (0x01..0x7D)")
        return self


class SecurityNrcCase(BaseModel):
    """Datengetriebener NRC-Provokationsfall für die Security-Access-Testsuite."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    enabled: bool = True
    expected_nrc: int | str | None = Field(None, description="None = positiver Referenzfall")
    steps: list[dict[str, Any]] | None = Field(
        None, description="Eigene Schritte (überschreiben den Standardablauf)"
    )


class EcuDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = ""
    description: str = ""
    isotp: str | IsoTpProfile = Field(..., description="Name eines ISO-TP-Profils oder Inline-Profil")
    functional_group: str | None = Field(
        None, description="ECUs mit gleicher Gruppe antworten auf funktionale Anfragen"
    )
    sessions: list[SessionDef] = Field(default_factory=lambda: list(DEFAULT_SESSIONS))
    timing: UdsTiming | None = None
    tester_present: TesterPresentConfig | None = None
    security_levels: list[SecurityLevelDef] = Field(default_factory=list)
    security_nrc_cases: list[SecurityNrcCase] | None = None
    vars: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------------------------
# Konfig-Paket
# --------------------------------------------------------------------------------------------


class PackageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[A-Za-z0-9_.\-]+$")
    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""


class Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    package: PackageMeta
    isotp_profiles: dict[str, IsoTpProfile] = Field(default_factory=dict)
    ecus: list[EcuDef] = Field(default_factory=list)
    security_providers: list[SecurityProviderDef] = Field(default_factory=list)
    catalogs: Catalogs = Field(default_factory=Catalogs)
    messages: list[MessageDef] = Field(default_factory=list)
    sequences: list[SequenceDef] = Field(default_factory=list)
    tests: list[TestDef] = Field(default_factory=list)
    testsuites: list[SuiteDef] = Field(default_factory=list)
    simulation: SimulationConfig = Field(default_factory=SimulationConfig)
    dashboards: list[Dashboard] = Field(default_factory=list, description="Vordefinierte Dashboards/Panels")

    @model_validator(mode="before")
    @classmethod
    def _profile_names(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("isotp_profiles"), dict):
            for name, prof in data["isotp_profiles"].items():
                if isinstance(prof, dict):
                    prof.setdefault("name", name)
        return data

    @model_validator(mode="after")
    def _refs(self) -> Package:
        errs: list[str] = []
        for kind, items in (
            ("ecus", self.ecus),
            ("messages", self.messages),
            ("sequences", self.sequences),
            ("tests", self.tests),
            ("testsuites", self.testsuites),
            ("security_providers", self.security_providers),
        ):
            seen: set[str] = set()
            for it in items:
                if it.id in seen:
                    errs.append(f"{kind}: doppelte ID {it.id!r}")
                seen.add(it.id)
        for ecu in self.ecus:
            if isinstance(ecu.isotp, str) and ecu.isotp not in self.isotp_profiles:
                errs.append(f"ECU {ecu.id!r}: ISO-TP-Profil {ecu.isotp!r} nicht definiert")
        for kind, keys in (
            ("dids", [d.id for d in self.catalogs.dids]),
            ("dtcs", [d.code for d in self.catalogs.dtcs]),
            ("routines", [r.id for r in self.catalogs.routines]),
        ):
            if len(keys) != len(set(keys)):
                errs.append(f"Katalog {kind}: doppelte Einträge")
        if errs:
            raise ValueError("; ".join(errs))
        return self


# --------------------------------------------------------------------------------------------
# App-Konfiguration
# --------------------------------------------------------------------------------------------


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "127.0.0.1"
    port: int = 8765
    token: str | None = Field(None, description="API-Token; leer = nur lokal ohne Token. Env: UDSBENCH_TOKEN")
    open_browser: bool = False
    cors_origins: list[str] = Field(default_factory=list)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dir: str = "logs"
    console: bool = True
    json_files: bool = True
    max_bytes: int = 10 * 1024 * 1024
    backups: int = 5
    buffer_size: int = 5000
    mask_secrets: bool = True
    mask_fields: list[str] = Field(
        default_factory=lambda: ["seed", "key", "password", "token", "secret", "credential"]
    )


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: str = "data"
    package_dirs: list[str] = Field(default_factory=lambda: ["config/packages"])
    recordings_dir: str = "recordings"
    reports_dir: str = "reports"
    plugins_dir: str = "config/plugins"
    providers_dir: str = "config/providers"


class ConnectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    backend: Literal["virtual", "python-can"] = "virtual"
    options: dict[str, Any] = Field(default_factory=dict)
    simulate: bool = Field(
        False, description="ECU-Testdouble der aktiven Pakete auf diesem (virtuellen) Bus starten"
    )


class TraceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buffer_size: int = 100_000
    ws_batch_ms: int = 50
    ws_max_batch: int = 2000


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: ServerConfig = Field(default_factory=ServerConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    timing: UdsTiming = Field(default_factory=UdsTiming)
    tester_present: TesterPresentConfig = Field(default_factory=TesterPresentConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    connections: list[ConnectionSpec] = Field(
        default_factory=list, description="Beim Start automatisch verbinden"
    )
    active_packages: list[str] | None = Field(
        None, description="Beim Start aktivieren (None = zuletzt aktive)"
    )
    language: str = "de"
