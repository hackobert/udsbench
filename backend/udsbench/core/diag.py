"""ECU-Laufzeitobjekte: Transport, UDS-Client, Session-/Security-Zustand, TesterPresent (S3)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from ..config.packages import EcuRuntimeDef
from ..config.schema import TesterPresentConfig, UdsTiming
from ..core.errors import NotConnectedError, NotFoundError
from ..isotp.transport import IsoTpTransport
from ..uds.client import TimingState, UdsClient, UdsResult
from ..uds.services import SESSION_NAMES

if TYPE_CHECKING:
    from .platform import Platform

log = logging.getLogger("udsbench.app.diag")
audit = logging.getLogger("udsbench.audit")


class EcuRuntime:
    def __init__(self, platform: Platform, rdef: EcuRuntimeDef) -> None:
        self.platform = platform
        self.rdef = rdef
        self.id = rdef.ecu.id
        channel = platform.connections.get(rdef.profile.channel)
        self.transport = IsoTpTransport(
            channel,
            rdef.profile,
            name=self.id,
            on_event=lambda k, d: platform.events.publish("isotp", kind=k, **d),
        )
        self.transport.start()
        t: UdsTiming = rdef.ecu.timing or platform.config.timing
        self.timing_cfg = t
        self.timing = TimingState(
            t.p2_ms, t.p2_star_ms, t.margin_ms, t.max_response_pending, t.await_nrc_on_suppress
        )
        self.tp_cfg: TesterPresentConfig = rdef.ecu.tester_present or platform.config.tester_present
        self.client = UdsClient(
            self.id, self.transport, self.timing, lambda: platform.packages.merged.catalogs, t.validation
        )
        self.session = 0x01
        self.unlocked: set[int] = set()
        self.last_seed: dict[int, bytes] = {}
        self.tp_enabled = self.tp_cfg.enabled
        self.tp_sent = 0
        self._tp_task: asyncio.Task[None] | None = asyncio.get_running_loop().create_task(self._tp_loop())

    # ------------------------------------------------------------------------------------
    def close(self) -> None:
        if self._tp_task:
            self._tp_task.cancel()
            self._tp_task = None
        self.transport.stop()

    def session_name(self, sid: int | None = None) -> str:
        sid = self.session if sid is None else sid
        for s in self.rdef.ecu.sessions:
            if s.id == sid:
                return s.name
        return SESSION_NAMES.get(sid, f"session 0x{sid:02X}")

    def resolve_session(self, ref: int | str) -> int:
        if isinstance(ref, int):
            return ref
        for s in self.rdef.ecu.sessions:
            if s.name.lower() == str(ref).lower():
                return s.id
        from .hexutil import parse_int

        return parse_int(ref)

    def state(self) -> dict[str, Any]:
        p = self.rdef.profile
        return {
            "id": self.id,
            "name": self.rdef.ecu.name,
            "package": self.rdef.package,
            "channel": p.channel,
            "tx_id": p.tx_id,
            "rx_id": p.rx_id,
            "functional_id": p.functional_id,
            "isotp_profile": p.name,
            "session": self.session,
            "session_name": self.session_name(),
            "unlocked_levels": sorted(self.unlocked),
            "timing": self.timing.to_dict(),
            "tester_present": {"enabled": self.tp_enabled, **self.tp_cfg.model_dump(), "sent": self.tp_sent},
            "last_activity": self.client.last_activity,
            "transport_errors": self.transport.errors[-10:],
        }

    def set_session(self, sid: int, reason: str = "") -> None:
        if sid != self.session:
            old = self.session
            self.session = sid
            if self.unlocked:
                audit.info(
                    "Security-Zustand von %s zurückgesetzt (Sessionwechsel)", self.id, extra={"ecu": self.id}
                )
            self.unlocked.clear()
            self.platform.events.publish(
                "session", ecu=self.id, session=sid, name=self.session_name(), previous=old, reason=reason
            )
            log.info("%s: Session 0x%02X → 0x%02X (%s) %s", self.id, old, sid, self.session_name(), reason)

    # ------------------------------------------------------------------------------------
    async def request(
        self,
        payload: bytes,
        *,
        functional: bool = False,
        timeout_ms: float | None = None,
        validate: str | None = None,
        expect_response: bool | None = None,
    ) -> UdsResult:
        peers = self.platform.diag.functional_peers(self) if functional else None
        res = await self.client.request(
            payload,
            timeout_ms=timeout_ms,
            validate=validate,
            functional_peers=peers,
            expect_response=expect_response,
        )
        self._post(res)
        if functional:
            for r in res.responses:
                rt = self.platform.diag.runtimes.get(r.ecu)
                if rt and rt is not self:
                    rt._post_payload(payload, r.payload)
        self.platform.events.publish("uds", result=res.to_dict())
        return res

    def _post(self, res: UdsResult) -> None:
        if res.response is not None:
            self._post_payload(res.request, res.response)
        elif res.suppress_positive and not res.error:
            # unterdrückte positive Antwort: Zustandswechsel annehmen
            self._post_payload(res.request, bytes([(res.request[0] + 0x40) & 0xFF, res.request[1] & 0x7F]))

    def _post_payload(self, req: bytes, resp: bytes) -> None:
        if not resp or resp[0] != (req[0] + 0x40) & 0xFF:
            return
        sid = req[0]
        if sid == 0x10 and len(resp) >= 2:
            if len(resp) >= 6 and self.timing_cfg.adopt_server_timing:
                p2 = int.from_bytes(resp[2:4], "big")
                p2s = int.from_bytes(resp[4:6], "big") * 10
                if p2 > 0:
                    self.timing.p2_ms = p2
                if p2s > 0:
                    self.timing.p2_star_ms = p2s
            self.set_session(resp[1] & 0x7F, "DiagnosticSessionControl")
        elif sid == 0x11 and len(req) >= 2 and (req[1] & 0x7F) in (0x01, 0x02, 0x03):
            self.set_session(0x01, "ECUReset")
            self.timing.p2_ms = self.timing_cfg.p2_ms
            self.timing.p2_star_ms = self.timing_cfg.p2_star_ms
        elif sid == 0x27 and len(resp) >= 2:
            lvl = resp[1] & 0x7F
            if lvl % 2:
                self.last_seed[lvl] = resp[2:]
                if resp[2:] and not any(resp[2:]):
                    self.unlocked.add(lvl)
            else:
                self.unlocked.add(lvl - 1)
                audit.info(
                    "%s: Security-Level 0x%02X entsperrt",
                    self.id,
                    lvl - 1,
                    extra={"ecu": self.id, "level": lvl - 1},
                )
                self.platform.events.publish("security", ecu=self.id, level=lvl - 1, unlocked=True)

    # ------------------------------------------------------------------------------------
    async def _tp_loop(self) -> None:
        """TesterPresent als Keep-Alive bei Nicht-Default-Session; S3-Rückfall ohne Keep-Alive."""
        while True:
            try:
                interval = self.tp_cfg.interval_ms / 1000.0
                await asyncio.sleep(min(0.1, interval / 4))
                if self.session == 0x01:
                    continue
                idle = time.time() - self.client.last_activity
                if not self.tp_enabled:
                    if idle > self.tp_cfg.s3_server_ms / 1000.0:
                        self.set_session(0x01, "S3-Timeout (kein TesterPresent)")
                    continue
                if idle < interval or self.client.lock.locked():
                    continue
                if not self.transport.channel.is_open:
                    continue
                sub = 0x80 if self.tp_cfg.suppress_response else 0x00
                functional = (
                    self.tp_cfg.addressing == "functional" and self.rdef.profile.functional_id is not None
                )
                res = await self.client.request(
                    bytes([0x3E, sub]),
                    validate="off",
                    functional_peers=[] if functional else None,
                    expect_response=not self.tp_cfg.suppress_response,
                )
                self.tp_sent += 1
                if res.error and not self.tp_cfg.suppress_response:
                    log.warning("%s: TesterPresent ohne Antwort: %s", self.id, res.error)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - Keep-Alive darf nie abbrechen
                log.debug("TesterPresent-Fehler: %s", exc)
                await asyncio.sleep(0.5)


class DiagnosticsManager:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.runtimes: dict[str, EcuRuntime] = {}

    def rebuild(self) -> None:
        merged = self.platform.packages.merged
        conns = self.platform.connections
        keep: dict[str, EcuRuntime] = {}
        for ecu_id, rdef in merged.ecus.items():
            ch = conns.channels.get(rdef.profile.channel)
            if ch is None or not ch.is_open:
                continue
            old = self.runtimes.get(ecu_id)
            if (
                old
                and old.rdef.profile == rdef.profile
                and old.transport.channel is ch
                and old.rdef.ecu == rdef.ecu
            ):
                old.rdef = rdef
                keep[ecu_id] = old
                continue
            if old:
                old.close()
            keep[ecu_id] = EcuRuntime(self.platform, rdef)
        for ecu_id, rt in self.runtimes.items():
            if ecu_id not in keep:
                rt.close()
        self.runtimes = keep

    def close_all(self) -> None:
        for rt in self.runtimes.values():
            rt.close()
        self.runtimes.clear()

    def get(self, ecu_id: str | None) -> EcuRuntime:
        merged = self.platform.packages.merged
        if ecu_id is None:
            if len(merged.ecus) == 1:
                ecu_id = next(iter(merged.ecus))
            else:
                raise NotFoundError("Keine ECU angegeben (mehrere/keine ECUs konfiguriert)")
        if ecu_id not in merged.ecus:
            raise NotFoundError(f"ECU {ecu_id!r} ist in keinem aktiven Paket definiert")
        rt = self.runtimes.get(ecu_id)
        if rt is None:
            self.rebuild()
            rt = self.runtimes.get(ecu_id)
        if rt is None:
            ch = merged.ecus[ecu_id].profile.channel
            raise NotConnectedError(f"Kanal {ch!r} der ECU {ecu_id!r} ist nicht verbunden")
        return rt

    def functional_peers(self, rt: EcuRuntime) -> list[tuple[str, IsoTpTransport]]:
        group = rt.rdef.ecu.functional_group
        fid = rt.rdef.profile.functional_id
        peers = []
        for other in self.runtimes.values():
            same_group = group is not None and other.rdef.ecu.functional_group == group
            same_fid = group is None and fid is not None and other.rdef.profile.functional_id == fid
            if (
                other is rt or same_group or same_fid
            ) and other.rdef.profile.channel == rt.rdef.profile.channel:
                peers.append((other.id, other.transport))
        return peers

    def states(self) -> list[dict[str, Any]]:
        out = []
        for ecu_id, rdef in self.platform.packages.merged.ecus.items():
            rt = self.runtimes.get(ecu_id)
            if rt:
                out.append({**rt.state(), "connected": True})
            else:
                p = rdef.profile
                out.append(
                    {
                        "id": ecu_id,
                        "name": rdef.ecu.name,
                        "package": rdef.package,
                        "channel": p.channel,
                        "tx_id": p.tx_id,
                        "rx_id": p.rx_id,
                        "functional_id": p.functional_id,
                        "isotp_profile": p.name,
                        "connected": False,
                    }
                )
        return out
