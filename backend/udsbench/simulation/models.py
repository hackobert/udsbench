"""Konfiguration des simulierten ECU-Testdoubles."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.types import HexByte, HexInt


class SimDid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: HexInt
    value: str = Field("", description="Hex-Rohwert")
    writable: bool = False
    sessions: list[HexByte] | None = Field(None, description="Erlaubte Sessions (None = alle)")
    security_level: int | None = Field(None, description="Für Schreiben benötigtes Seed-Level")
    read_security_level: int | None = None
    length: int | None = Field(None, description="Erwartete Länge beim Schreiben")


class SimDtc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: HexInt
    status: HexByte = 0x09
    snapshot: str = ""
    extended: str = ""


class SimRoutine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: HexInt
    result: str = Field("", description="Hex-Statusrecord in der Antwort")
    sessions: list[HexByte] | None = None
    security_level: int | None = None
    requires_start: bool = Field(True, description="Stop/Results nur nach Start (sonst NRC 0x24)")
    pending: int = Field(0, description="Anzahl 0x78 vor der Antwort")


class SimSecurityLevel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(..., description="Seed-Subfunktion (ungerade)")
    seed_length: int = 4
    provider: str = Field("demo", description="Provider-ID oder Typ zur Key-Prüfung")
    params: dict[str, Any] = Field(default_factory=dict)
    sessions: list[HexByte] | None = Field(None, description="Erlaubte Sessions (None = alle außer default)")
    max_attempts: int = 3
    lockout_ms: int = 10000
    static_seed: str | None = Field(None, description="Fester Seed (Hex) für reproduzierbare Tests")


class SimOverride(BaseModel):
    """Erzwingt eine Antwort für passende Requests (Fehlerinjektion)."""

    model_config = ConfigDict(extra="forbid")
    match: str = Field(..., description="Request-Muster (Hex, '??' Wildcard, '*' am Ende)")
    respond: str | None = Field(None, description="Antwort (Hex); None = keine Antwort")
    pending: int = 0
    delay_ms: int = 0
    times: int | None = Field(None, description="Wie oft (None = immer)")


class SimEcuConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ecu: str = Field(..., description="Referenz auf eine ECU-Definition (für IDs/ISO-TP-Profil)")
    enabled: bool = True
    sessions: list[HexByte] = Field(default_factory=lambda: [0x01, 0x02, 0x03])
    p2_server_max_ms: int = 50
    p2_star_server_max_ms: int = 5000
    s3_server_ms: int = 5000
    response_delay_ms: int = 0
    services: list[HexByte] | None = Field(None, description="Unterstützte SIDs (None = alle simulierten)")
    service_sessions: dict[HexByte, list[HexByte]] = Field(
        default_factory=dict, description="SID → erlaubte Sessions (sonst NRC 0x7F)"
    )
    dids: list[SimDid] = Field(default_factory=list)
    dtcs: list[SimDtc] = Field(default_factory=list)
    routines: list[SimRoutine] = Field(default_factory=list)
    security: list[SimSecurityLevel] = Field(default_factory=list)
    memory_size: int = Field(0x10000, description="Größe des simulierten Speichers (0x23/0x3D/0x34-0x37)")
    max_block_length: int = 0x102
    overrides: list[SimOverride] = Field(default_factory=list)
    dtc_status_availability_mask: HexByte = 0xFF


class SimulationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ecus: list[SimEcuConfig] = Field(default_factory=list)
