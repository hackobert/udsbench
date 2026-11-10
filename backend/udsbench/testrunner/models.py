"""Deklaratives Testformat (YAML/JSON)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..messages.models import Step


class TestDef(BaseModel):
    __test__ = False  # kein pytest-Testklassen-Kandidat
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = ""
    description: str = ""
    ecu: str | None = None
    tags: list[str] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)
    datasets: list[dict[str, Any]] = Field(
        default_factory=list, description="Datengetrieben: je Datensatz ein Durchlauf"
    )
    preconditions: list[Step] = Field(
        default_factory=list, description="Vorbedingungen (Fehler → Test 'error')"
    )
    setup: list[Step] = Field(default_factory=list)
    steps: list[Step]
    teardown: list[Step] = Field(default_factory=list)
    repeat: int = Field(1, ge=1)
    abort_on_failure: bool = Field(
        True, description="Bei fehlgeschlagenem Schritt restliche Schritte überspringen"
    )
    timeout_s: float | None = None
    expected_result: str = Field("pass", description="'pass' oder 'fail' (Negativtest)")


class SuiteDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = ""
    description: str = ""
    ecu: str | None = None
    tests: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="Zusätzlich alle Tests mit diesen Tags")
    vars: dict[str, Any] = Field(default_factory=dict)
    setup: list[Step] = Field(default_factory=list)
    teardown: list[Step] = Field(default_factory=list)
    stop_on_failure: bool = False
