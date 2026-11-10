"""Benutzerdefinierte Dashboards: Panels mit eigenen Knöpfen, Wertanzeigen, Diagrammen …"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ActionType = Literal[
    "message",
    "sequence",
    "test",
    "suite",
    "uds",
    "unlock",
    "session",
    "step",
    "raw",
    "marker",
    "record_start",
    "record_stop",
    "report",
]


class Action(BaseModel):
    """Was ein Knopf auslöst. ``ref`` ist je nach Typ Botschafts-/Sequenz-/Test-/Suite-ID, Level oder Session."""

    model_config = ConfigDict(extra="forbid")
    type: ActionType
    ref: str | int | None = None
    ecu: str | None = None
    payload: str | None = Field(None, description="Hex-Nutzlast (type uds/raw), Platzhalter erlaubt")
    functional: bool = False
    vars: dict[str, Any] = Field(default_factory=dict)
    step: dict[str, Any] | None = Field(None, description="Beliebiger Schritt (type step)")
    can_id: str | int | None = Field(None, description="CAN-ID (type raw)")
    channel: str = "default"
    confirm: bool = Field(False, description="Vor dem Auslösen nachfragen")
    report: dict[str, Any] | None = Field(None, description="Report-Spezifikation (type report)")

    @model_validator(mode="after")
    def _check(self) -> Action:
        need_ref = {"message", "sequence", "test", "suite", "unlock", "session"}
        if self.type in need_ref and self.ref is None:
            raise ValueError(f"Aktion {self.type!r} benötigt 'ref'")
        if self.type in ("uds", "raw") and not self.payload:
            raise ValueError(f"Aktion {self.type!r} benötigt 'payload'")
        if self.type == "raw" and self.can_id is None:
            raise ValueError("Aktion 'raw' benötigt 'can_id'")
        if self.type == "step" and not self.step:
            raise ValueError("Aktion 'step' benötigt 'step'")
        return self


class Button(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    action: Action
    color: str | None = Field(None, description="z. B. 'primary', 'success', 'danger' oder CSS-Farbe")
    icon: str | None = None
    shortcut: str | None = Field(None, description="Tastenkürzel, z. B. 'ctrl+1'")
    description: str = ""


PanelType = Literal[
    "buttons", "values", "timechart", "stats", "events", "trace", "ecu_status", "log", "note", "run_status"
]


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str = ""
    type: PanelType
    x: int = Field(0, ge=0, description="Spalte im Raster")
    y: int = Field(0, ge=0, description="Zeile im Raster")
    w: int = Field(4, ge=1, le=12, description="Breite (von 12 Spalten)")
    h: int = Field(3, ge=1, le=24, description="Höhe (Rasterzeilen)")
    buttons: list[Button] = Field(default_factory=list, description="type buttons")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Typabhängig: values {ecu, dids:[…], refresh_ms}; timechart {metric: uds|frames|events, group_by: type|service|ecu|nrc_name, "
            "window_s, bucket_s, ecu}; stats {window_s, ecu}; events {topics:[…], limit}; trace {filter:{…}, view}; "
            "ecu_status {ecus:[…]}; log {channel, level}; note {text}; run_status {limit}"
        ),
    )


class Dashboard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[A-Za-z0-9_.\-]+$")
    name: str
    description: str = ""
    columns: int = Field(12, ge=1, le=24)
    panels: list[Panel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> Dashboard:
        ids = [p.id for p in self.panels]
        if len(ids) != len(set(ids)):
            raise ValueError("Panel-IDs müssen eindeutig sein")
        return self
