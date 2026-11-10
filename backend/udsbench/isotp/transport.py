"""Asynchroner ISO-TP-Transport (ISO 15765-2) auf einem CAN-Kanal.

Unterstützt SF/FF/CF/FC inkl. Blocksize, STmin (ms und µs), FC.WAIT/OVFLW, N_As/N_Bs/N_Cr-Timeouts,
normale/extended/mixed Adressierung, 11/29-Bit-IDs und CAN-FD.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..can.channel import CanChannel
from ..can.frame import CanFrame
from .codec import (
    FlowStatus,
    IsoTpError,
    PciType,
    cf_capacity,
    encode_consecutive_frame,
    encode_first_frame,
    encode_flow_control,
    encode_single_frame,
    parse_frame,
    stmin_to_seconds,
)
from .profile import IsoTpProfile

log = logging.getLogger("udsbench.app.isotp")


class IsoTpTimeout(IsoTpError):
    def __init__(self, message: str, timer: str) -> None:
        super().__init__(message, "timeout")
        self.timer = timer


@dataclass
class IsoTpMessage:
    payload: bytes
    can_id: int
    t_first: float
    t_last: float
    frames: int


EventCallback = Callable[[str, dict[str, Any]], None]


class IsoTpTransport:
    def __init__(
        self,
        channel: CanChannel,
        profile: IsoTpProfile,
        *,
        name: str = "",
        rx_id: int | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self.channel = channel
        self.profile = profile
        self.name = name or profile.name
        self.rx_id = profile.rx_id if rx_id is None else rx_id
        self.on_event = on_event
        self.rx_queue: asyncio.Queue[IsoTpMessage] = asyncio.Queue()
        self._tx_lock = asyncio.Lock()
        self._fc_future: asyncio.Future[tuple[int, int, int]] | None = None
        # Empfangszustand
        self._rx_buf = bytearray()
        self._rx_len = 0
        self._rx_seq = 0
        self._rx_block_count = 0
        self._rx_t_first = 0.0
        self._rx_frames = 0
        self._rx_timer: asyncio.TimerHandle | None = None
        self._rx_active = False
        self._started = False
        self.errors: list[dict[str, Any]] = []

    # ------------------------------------------------------------------------------------
    def start(self) -> None:
        if not self._started:
            self.channel.add_listener(self._on_frame)
            self._started = True

    def stop(self) -> None:
        if self._started:
            self.channel.remove_listener(self._on_frame)
            self._started = False
        self._reset_rx()

    def update_profile(self, profile: IsoTpProfile) -> None:
        self.profile = profile
        self.rx_id = profile.rx_id

    def flush(self) -> None:
        while not self.rx_queue.empty():
            self.rx_queue.get_nowait()

    def _emit(self, kind: str, **data: Any) -> None:
        if kind.startswith("error"):
            self.errors.append({"kind": kind, **data, "ts": time.time()})
            del self.errors[:-50]
            log.warning("ISO-TP %s [%s]: %s", self.name, kind, data)
        if self.on_event:
            self.on_event(kind, {"transport": self.name, **data})

    # ------------------------------------------------------------------------------------
    # Senden
    # ------------------------------------------------------------------------------------
    async def _send_raw(self, data: bytes, can_id: int | None = None) -> None:
        p = self.profile
        frame = CanFrame(
            arbitration_id=p.tx_id if can_id is None else can_id,
            data=data,
            is_extended_id=p.extended_id,
            is_fd=p.can_fd,
            bitrate_switch=p.can_fd and p.bitrate_switch,
        )
        await self.channel.send(frame, timeout=p.timeouts.n_as / 1000.0)

    async def send(self, payload: bytes, functional: bool = False) -> float:
        """Sendet eine Nachricht. Gibt den Zeitpunkt der vollständigen Übertragung zurück."""
        p = self.profile
        async with self._tx_lock:
            sf = encode_single_frame(payload, p, functional)
            if functional:
                if sf is None:
                    raise IsoTpError("Funktionale Anfrage passt nicht in einen Single Frame", "argument")
                if p.functional_id is None:
                    raise IsoTpError(f"Profil {p.name!r} hat keine functional_id", "argument")
                await self._send_raw(sf, p.functional_id)
                return time.time()
            if sf is not None:
                await self._send_raw(sf)
                return time.time()
            if len(payload) > 0xFFFFFFFF:
                raise IsoTpError("Nachricht zu lang", "argument")
            ff, pos = encode_first_frame(payload, p)
            loop = asyncio.get_running_loop()
            self._fc_future = loop.create_future()
            await self._send_raw(ff)
            seq = 1
            cap = cf_capacity(p)
            try:
                while pos < len(payload):
                    bs, st = await self._await_cts()
                    st_s = stmin_to_seconds(p.st_min_tx_override if p.st_min_tx_override is not None else st)
                    sent_in_block = 0
                    while pos < len(payload) and (bs == 0 or sent_in_block < bs):
                        if sent_in_block or st_s:
                            await asyncio.sleep(st_s)
                        chunk = payload[pos : pos + cap]
                        last_in_block = bs != 0 and sent_in_block + 1 == bs and pos + cap < len(payload)
                        if last_in_block:
                            # Future vor dem Senden anlegen, damit ein sehr schnelles FC nicht verloren geht
                            self._fc_future = loop.create_future()
                        await self._send_raw(encode_consecutive_frame(chunk, seq, p))
                        pos += cap
                        seq = (seq + 1) & 0x0F
                        sent_in_block += 1
            finally:
                self._fc_future = None
            return time.time()

    async def _await_cts(self) -> tuple[int, int]:
        p = self.profile
        waits = 0
        while True:
            fut = self._fc_future
            assert fut is not None
            try:
                status, bs, st = await asyncio.wait_for(fut, p.timeouts.n_bs / 1000.0)
            except TimeoutError:
                self._emit("error.timeout", timer="N_Bs", message="Kein Flow Control empfangen")
                raise IsoTpTimeout("N_Bs-Timeout: kein Flow Control empfangen", "N_Bs") from None
            if status == FlowStatus.CTS:
                return bs, st
            if status == FlowStatus.WAIT:
                waits += 1
                if waits > p.wft_max:
                    self._emit("error.wft_max", message="N_WFTmax überschritten")
                    raise IsoTpError("Zu viele FC.WAIT (N_WFTmax überschritten)", "wft_ovrn")
                self._fc_future = asyncio.get_running_loop().create_future()
                continue
            if status == FlowStatus.OVFLW:
                self._emit("error.overflow", message="Empfänger meldet Overflow")
                raise IsoTpError("Empfänger meldet FC.OVFLW (Puffer zu klein)", "overflow")
            self._emit("error.invalid_fs", status=status)
            raise IsoTpError(f"Ungültiger Flow-Status {status}", "invalid_fs")

    # ------------------------------------------------------------------------------------
    # Empfangen
    # ------------------------------------------------------------------------------------
    async def receive(self, timeout: float | None) -> IsoTpMessage:
        try:
            if timeout is None:
                return await self.rx_queue.get()
            return await asyncio.wait_for(self.rx_queue.get(), timeout)
        except TimeoutError:
            raise IsoTpTimeout("Keine Nachricht empfangen", "receive") from None

    def _matches(self, frame: CanFrame) -> bool:
        p = self.profile
        if (
            frame.direction != "rx"
            or frame.arbitration_id != self.rx_id
            or frame.is_extended_id != p.extended_id
        ):
            return False
        if frame.is_error_frame or frame.is_remote_frame:
            return False
        if p.addressing != "normal" and p.rx_address_extension is not None:
            return len(frame.data) > 0 and frame.data[0] == p.rx_address_extension
        return True

    def _reset_rx(self) -> None:
        self._rx_active = False
        self._rx_buf = bytearray()
        if self._rx_timer:
            self._rx_timer.cancel()
            self._rx_timer = None

    def _arm_ncr(self) -> None:
        if self._rx_timer:
            self._rx_timer.cancel()
        loop = asyncio.get_running_loop()
        self._rx_timer = loop.call_later(self.profile.timeouts.n_cr / 1000.0, self._on_ncr_timeout)

    def _on_ncr_timeout(self) -> None:
        if self._rx_active:
            self._emit("error.timeout", timer="N_Cr", received=len(self._rx_buf), expected=self._rx_len)
        self._reset_rx()

    def _send_fc_later(self, status: int) -> None:
        p = self.profile
        data = encode_flow_control(status, p.block_size, p.st_min, p)
        task = asyncio.get_running_loop().create_task(self._send_raw(data))
        task.add_done_callback(_log_task_error)

    def _on_frame(self, frame: CanFrame) -> None:
        if not self._matches(frame):
            return
        try:
            info = parse_frame(frame.data, self.profile.addressing)
        except IsoTpError as exc:
            self._emit("error.format", message=str(exc))
            return
        if info.pci_type == PciType.FC:
            if self._fc_future and not self._fc_future.done():
                self._fc_future.set_result((info.flow_status or 0, info.block_size or 0, info.st_min or 0))
            else:
                self._emit("unexpected", pci="FC")
            return
        if info.pci_type == PciType.SF:
            if self._rx_active:
                self._emit(
                    "error.unexpected", pci="SF", message="SF während laufender Segmentierung – Abbruch"
                )
                self._reset_rx()
            self.rx_queue.put_nowait(
                IsoTpMessage(info.data, frame.arbitration_id, frame.timestamp, frame.timestamp, 1)
            )
            return
        if info.pci_type == PciType.FF:
            if self._rx_active:
                self._emit(
                    "error.unexpected", pci="FF", message="FF während laufender Segmentierung – Neustart"
                )
                self._reset_rx()
            length = info.length or 0
            if length > self.profile.max_rx_length:
                self._send_fc_later(FlowStatus.OVFLW)
                self._emit("error.overflow", length=length)
                return
            self._rx_active = True
            self._rx_len = length
            self._rx_buf = bytearray(info.data[:length])
            self._rx_seq = 1
            self._rx_block_count = 0
            self._rx_t_first = frame.timestamp
            self._rx_frames = 1
            self._send_fc_later(FlowStatus.CTS)
            self._arm_ncr()
            return
        if info.pci_type == PciType.CF:
            if not self._rx_active:
                self._emit("unexpected", pci="CF")
                return
            if info.seq != self._rx_seq:
                self._emit("error.sequence", expected=self._rx_seq, received=info.seq)
                self._reset_rx()
                return
            self._rx_seq = (self._rx_seq + 1) & 0x0F
            self._rx_frames += 1
            remaining = self._rx_len - len(self._rx_buf)
            self._rx_buf += info.data[:remaining]
            if len(self._rx_buf) >= self._rx_len:
                msg = IsoTpMessage(
                    bytes(self._rx_buf),
                    frame.arbitration_id,
                    self._rx_t_first,
                    frame.timestamp,
                    self._rx_frames,
                )
                self._reset_rx()
                self.rx_queue.put_nowait(msg)
                return
            self._rx_block_count += 1
            bs = self.profile.block_size
            if bs and self._rx_block_count >= bs:
                self._rx_block_count = 0
                self._send_fc_later(FlowStatus.CTS)
            self._arm_ncr()


def _log_task_error(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        exc = task.exception()
        if exc:
            log.warning("Senden des Flow-Control-Frames fehlgeschlagen: %s", exc)
