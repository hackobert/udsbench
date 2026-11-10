"""Datenmodelle für vordefinierte Botschaften, Sequenzen/Makros und Schritte."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.types import HexInt


class CustomAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class Expect(BaseModel):
    """Assertions zu einem Schritt. Alle angegebenen Kriterien müssen erfüllt sein."""

    model_config = ConfigDict(extra="forbid")
    positive: bool | None = Field(None, description="true: positive Response erwartet; false: negative")
    nrc: int | str | list[int | str] | None = Field(
        None, description="Erwarteter NRC (Zahl oder Name, auch Liste)"
    )
    response: str | None = Field(
        None, description="Exaktes Muster, '??' = beliebiges Byte, '*' am Ende = beliebiger Rest"
    )
    response_prefix: str | None = None
    length: int | None = None
    min_length: int | None = None
    max_time_ms: float | None = None
    min_time_ms: float | None = None
    no_response: bool | None = Field(None, description="true: Timeout/keine Antwort erwartet")
    pending_max: int | None = Field(None, description="Max. Anzahl 0x78-Antworten")
    expr: str | list[str] | None = Field(None, description="Boolesche Ausdrücke über response, data, vars …")
    fields: dict[str, Any] | None = Field(None, description="Pfad im dekodierten Ergebnis → erwarteter Wert")
    responses_min: int | None = Field(None, description="Mindestanzahl Antworten (funktional)")
    custom: list[CustomAssertion] | None = None


class SendAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str | None = Field(None, description="ID einer vordefinierten Botschaft")
    payload: str | None = Field(None, description="Hex-Nutzlast mit ${...}-Platzhaltern")
    functional: bool = False
    vars: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one(self) -> SendAction:
        if (self.message is None) == (self.payload is None):
            raise ValueError("send: genau eines von 'message' oder 'payload' angeben")
        return self


class RawFrameAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: HexInt
    data: str
    extended: bool = False
    fd: bool = False
    channel: str | None = None


class SendKeyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(..., description="Seed-Level (ungerade); gesendet wird level+1")
    key: str | None = Field(
        None, description="Ausdruck/Hex für den Key; leer = per Provider aus ${seed} berechnen"
    )


class ComputeKeyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int
    seed: str = "seed"
    provider: str | None = None
    save_as: str = "key"


class WriteDidAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    did: int | str
    value: Any = None
    raw: str | None = None


class RoutineAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | str
    action: Literal["start", "stop", "results"] = "start"
    params: dict[str, Any] = Field(default_factory=dict)
    raw: str | None = None


class ReadDtcAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subfunction: HexInt = 0x02
    mask: HexInt = 0xFF
    extra: str | None = None


class IoControlAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    did: int | str
    parameter: HexInt = 0x03
    value: Any = None
    raw: str | None = None


class TransferAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["download", "upload"] = "download"
    address: HexInt
    size: HexInt | None = None
    data: str | None = Field(None, description="Hex-Daten (Download) oder Ausdruck")
    file: str | None = Field(None, description="Datei relativ zum Datenverzeichnis")
    alfid: HexInt = 0x44
    data_format: HexInt = 0x00
    block_length: int | None = Field(None, description="Überschreibt maxNumberOfBlockLength der ECU")
    save_as: str = "transfer"


class IfAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: str
    then: list[Step] = Field(default_factory=list)
    else_: list[Step] = Field(default_factory=list, alias="else")


class RepeatAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = 1
    until: str | None = None
    steps: list[Step] = Field(default_factory=list)
    var: str = "i"


class SubSequenceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    vars: dict[str, Any] = Field(default_factory=dict)


ACTION_KEYS = (
    "send",
    "raw",
    "wait",
    "set",
    "session",
    "reset",
    "unlock",
    "request_seed",
    "send_key",
    "compute_key",
    "read_did",
    "write_did",
    "routine",
    "read_dtc",
    "clear_dtc",
    "io_control",
    "transfer",
    "sequence",
    "if_",
    "repeat",
    "log",
    "assert_",
    "tester_present",
)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = None
    ecu: str | None = None
    expect: Expect | None = None
    save: dict[str, str] | None = Field(None, description="Variable → Ausdruck (z. B. 'response[2:]')")
    continue_on_failure: bool = False
    retries: int = 0
    timeout_ms: float | None = None

    send: SendAction | None = None
    raw: RawFrameAction | None = None
    wait: float | None = Field(None, description="Wartezeit in ms")
    set: dict[str, Any] | None = None
    session: int | str | None = None
    reset: int | None = None
    unlock: int | None = Field(None, description="Kompletter Unlock für Seed-Level")
    request_seed: int | None = None
    send_key: SendKeyAction | None = None
    compute_key: ComputeKeyAction | None = None
    read_did: int | str | list[int | str] | None = None
    write_did: WriteDidAction | None = None
    routine: RoutineAction | None = None
    read_dtc: ReadDtcAction | None = None
    clear_dtc: HexInt | None = None
    io_control: IoControlAction | None = None
    transfer: TransferAction | None = None
    sequence: SubSequenceAction | str | None = None
    if_: IfAction | None = Field(None, alias="if")
    repeat: RepeatAction | None = None
    log: str | None = None
    assert_: str | list[str] | None = Field(None, alias="assert")
    tester_present: bool | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Step:
        present = [k for k in ACTION_KEYS if getattr(self, k) is not None]
        if len(present) != 1:
            raise ValueError(
                f"Ein Schritt braucht genau eine Aktion ({', '.join(a.rstrip('_') for a in ACTION_KEYS)}); gefunden: {present}"
            )
        return self

    @property
    def action(self) -> str:
        for k in ACTION_KEYS:
            if getattr(self, k) is not None:
                return k.rstrip("_")
        return "?"  # pragma: no cover

    def label(self) -> str:
        return self.name or self.action


class MessageDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = ""
    description: str = ""
    ecu: str | None = None
    payload: str = Field(..., description="Hex-Nutzlast, Platzhalter ${var} erlaubt")
    functional: bool = False
    vars: dict[str, Any] = Field(default_factory=dict, description="Default-Werte für Platzhalter")
    expect: Expect | None = None
    tags: list[str] = Field(default_factory=list)


class SequenceDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = ""
    description: str = ""
    ecu: str | None = None
    vars: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step]
    tags: list[str] = Field(default_factory=list)


IfAction.model_rebuild()
RepeatAction.model_rebuild()
Step.model_rebuild()
