"""UDS-Client (ISO 14229-1/-2): Request/Response mit P2/P2*-Handling, 0x78, SPRMIB, funktional."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..catalogs.view import CatalogView
from ..core.context import current
from ..core.errors import ValidationFailed
from ..core.hexutil import to_hex
from ..isotp.codec import IsoTpError
from ..isotp.transport import IsoTpTimeout, IsoTpTransport
from ..logs.setup import mask_uds
from .codec import NEGATIVE_RESPONSE_SID, decode_response, is_suppress_positive, validate_request
from .nrc import nrc_name

log = logging.getLogger("udsbench.comm.uds")


@dataclass
class TimingState:
    p2_ms: float
    p2_star_ms: float
    margin_ms: float
    max_pending: int
    await_nrc_on_suppress: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "p2_ms": self.p2_ms,
            "p2_star_ms": self.p2_star_ms,
            "margin_ms": self.margin_ms,
            "max_pending": self.max_pending,
        }


@dataclass
class EcuResponse:
    ecu: str
    payload: bytes
    t_rx: float
    pending_count: int = 0
    decoded: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ecu": self.ecu,
            "payload": to_hex(self.payload),
            "t_rx": self.t_rx,
            "pending_count": self.pending_count,
            "decoded": self.decoded,
        }


@dataclass
class UdsResult:
    ecu: str
    request: bytes
    functional: bool = False
    response: bytes | None = None
    responses: list[EcuResponse] = field(default_factory=list)
    pending_count: int = 0
    t_request: float = 0.0
    t_tx_done: float = 0.0
    t_response: float | None = None
    suppress_positive: bool = False
    error: str | None = None
    error_kind: str | None = None
    decoded: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cid: str | None = None

    @property
    def positive(self) -> bool:
        return self.response is not None and self.response[0] == (self.request[0] + 0x40) & 0xFF

    @property
    def negative(self) -> bool:
        return (
            self.response is not None
            and len(self.response) >= 1
            and self.response[0] == NEGATIVE_RESPONSE_SID
        )

    @property
    def nrc(self) -> int | None:
        if self.negative and self.response is not None and len(self.response) >= 3:
            return self.response[2]
        return None

    @property
    def elapsed_ms(self) -> float | None:
        if self.t_response is None:
            return None
        return round((self.t_response - self.t_tx_done) * 1000.0, 3)

    @property
    def total_ms(self) -> float:
        end = self.t_response or time.time()
        return round((end - self.t_request) * 1000.0, 3)

    @property
    def data(self) -> bytes:
        return self.response[1:] if self.response else b""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "ecu": self.ecu,
            "functional": self.functional,
            "request": to_hex(self.request),
            "response": to_hex(self.response) if self.response is not None else None,
            "positive": self.positive,
            "negative": self.negative,
            "nrc": self.nrc,
            "nrc_name": nrc_name(self.nrc) if self.nrc is not None else None,
            "pending_count": self.pending_count,
            "suppress_positive": self.suppress_positive,
            "elapsed_ms": self.elapsed_ms,
            "total_ms": self.total_ms,
            "t_request": self.t_request,
            "error": self.error,
            "error_kind": self.error_kind,
            "decoded": self.decoded,
            "responses": [r.to_dict() for r in self.responses],
            "warnings": self.warnings,
        }


class UdsClient:
    """Ein Client je ECU (physikalisch). Funktionale Anfragen sammeln über mehrere Transports."""

    def __init__(
        self,
        ecu: str,
        transport: IsoTpTransport,
        timing: TimingState,
        catalogs_getter: Any,
        validation: str = "strict",
    ) -> None:
        self.ecu = ecu
        self.transport = transport
        self.timing = timing
        self.catalogs_getter = catalogs_getter
        self.validation = validation
        self.lock = asyncio.Lock()
        self.last_activity = 0.0
        self.on_result: list[Any] = []

    @property
    def catalogs(self) -> CatalogView:
        return self.catalogs_getter()  # type: ignore[no-any-return]

    def _validate(self, payload: bytes, validate: str | None) -> list[str]:
        mode = validate or self.validation
        if mode == "off":
            return []
        v = validate_request(payload, strict=(mode == "strict"))
        if not v.ok:
            raise ValidationFailed("Request-Validierung fehlgeschlagen", details=v.errors)
        return v.warnings

    async def request(
        self,
        payload: bytes,
        *,
        timeout_ms: float | None = None,
        validate: str | None = None,
        functional_peers: list[tuple[str, IsoTpTransport]] | None = None,
        expect_response: bool | None = None,
    ) -> UdsResult:
        """Sendet eine Anfrage und wartet auf die Antwort(en).

        * P2-Timeout = ``timeout_ms`` oder (P2server_max + margin), ab Ende der Übertragung.
        * Nach jeder NRC 0x78 wird auf P2* + margin verlängert (max. ``max_pending``-mal).
        * Bei gesetztem SPRMIB wird optional P2 lang auf eine NRC gewartet.
        """
        functional = functional_peers is not None
        warnings = self._validate(payload, validate)
        res = UdsResult(
            self.ecu if not functional else "functional",
            payload,
            functional,
            cid=current(),
            warnings=warnings,
        )
        res.suppress_positive = is_suppress_positive(payload)
        t = self.timing
        p2 = (timeout_ms if timeout_ms is not None else t.p2_ms + t.margin_ms) / 1000.0
        p2s = (t.p2_star_ms + t.margin_ms) / 1000.0
        if expect_response is None:
            expect_response = not res.suppress_positive or t.await_nrc_on_suppress
        transports: list[tuple[str, IsoTpTransport]] = (
            functional_peers if functional_peers is not None else [(self.ecu, self.transport)]
        )
        async with self.lock:
            for _, tr in transports:
                tr.flush()
            res.t_request = time.time()
            log.info(
                "TX %s %s%s",
                res.ecu,
                mask_uds(payload),
                " (funktional)" if functional else "",
                extra={
                    "event": "uds.request",
                    "ecu": res.ecu,
                    "request": mask_uds(payload),
                    "functional": functional,
                },
            )
            try:
                res.t_tx_done = await self.transport.send(payload, functional=functional)
            except (IsoTpError, Exception) as exc:
                res.error = f"Senden fehlgeschlagen: {exc}"
                res.error_kind = getattr(exc, "kind", "transport")
                self.last_activity = time.time()
                self._log_result(res)
                return res
            self.last_activity = res.t_tx_done
            if not expect_response:
                self._log_result(res)
                return res
            if functional:
                await self._collect_functional(res, transports, p2, p2s)
            else:
                await self._collect_physical(res, p2, p2s)
            self.last_activity = time.time()
        if res.response is not None:
            res.decoded = decode_response(res.response, payload, self.catalogs)
        for r in res.responses:
            r.decoded = decode_response(r.payload, payload, self.catalogs)
        self._log_result(res)
        for cb in self.on_result:
            cb(res)
        return res

    def _matches(self, request: bytes, resp: bytes) -> bool:
        if not resp:
            return False
        if resp[0] == NEGATIVE_RESPONSE_SID:
            return len(resp) >= 2 and resp[1] == request[0]
        return resp[0] == (request[0] + 0x40) & 0xFF

    async def _collect_physical(self, res: UdsResult, p2: float, p2s: float) -> None:
        deadline = res.t_tx_done + p2
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                msg = await self.transport.receive(remaining)
            except IsoTpTimeout:
                break
            if not self._matches(res.request, msg.payload):
                res.warnings.append(f"Unerwartete Nachricht ignoriert: {to_hex(msg.payload)}")
                continue
            if msg.payload[0] == NEGATIVE_RESPONSE_SID and len(msg.payload) >= 3 and msg.payload[2] == 0x78:
                res.pending_count += 1
                log.info(
                    "RX %s %s (responsePending #%d)",
                    res.ecu,
                    mask_uds(msg.payload),
                    res.pending_count,
                    extra={"event": "uds.pending", "ecu": res.ecu},
                )
                if res.pending_count > self.timing.max_pending:
                    res.error = f"Zu viele ResponsePending (> {self.timing.max_pending})"
                    res.error_kind = "pending_limit"
                    return
                deadline = time.time() + p2s
                continue
            res.response = msg.payload
            res.t_response = msg.t_last
            return
        if res.suppress_positive:
            return  # keine Antwort ist bei SPRMIB korrekt
        res.error = (
            "Timeout: keine Antwort innerhalb P2"
            if res.pending_count == 0
            else "Timeout: keine Antwort innerhalb P2*"
        )
        res.error_kind = "timeout"

    async def _collect_functional(
        self, res: UdsResult, transports: list[tuple[str, IsoTpTransport]], p2: float, p2s: float
    ) -> None:
        async def one(ecu: str, tr: IsoTpTransport) -> EcuResponse | None:
            deadline = res.t_tx_done + p2
            pending = 0
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                try:
                    msg = await tr.receive(remaining)
                except IsoTpTimeout:
                    return None
                if not self._matches(res.request, msg.payload):
                    continue
                if (
                    msg.payload[0] == NEGATIVE_RESPONSE_SID
                    and len(msg.payload) >= 3
                    and msg.payload[2] == 0x78
                ):
                    pending += 1
                    if pending > self.timing.max_pending:
                        return None
                    deadline = time.time() + p2s
                    continue
                return EcuResponse(ecu, msg.payload, msg.t_last, pending)

        results = await asyncio.gather(*(one(e, tr) for e, tr in transports))
        res.responses = [r for r in results if r is not None]
        res.pending_count = sum(r.pending_count for r in res.responses)
        if res.responses:
            first = min(res.responses, key=lambda r: r.t_rx)
            res.response = first.payload
            res.t_response = first.t_rx
        elif not res.suppress_positive:
            res.error = "Timeout: keine Antwort auf funktionale Anfrage"
            res.error_kind = "timeout"

    def _log_result(self, res: UdsResult) -> None:
        if res.response is not None:
            log.info(
                "RX %s %s (%.1f ms%s)",
                res.ecu,
                mask_uds(res.response),
                res.elapsed_ms or 0,
                f", {res.pending_count}x pending" if res.pending_count else "",
                extra={
                    "event": "uds.response",
                    "ecu": res.ecu,
                    "request": mask_uds(res.request),
                    "response": mask_uds(res.response),
                    "elapsed_ms": res.elapsed_ms,
                    "pending": res.pending_count,
                    "nrc": res.nrc,
                },
            )
        elif res.error:
            log.warning(
                "%s %s: %s",
                res.ecu,
                mask_uds(res.request),
                res.error,
                extra={
                    "event": "uds.error",
                    "ecu": res.ecu,
                    "request": mask_uds(res.request),
                    "error": res.error,
                },
            )
