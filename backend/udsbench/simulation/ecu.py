"""Simuliertes ECU-Testdouble.

Läuft als eigener Knoten auf dem virtuellen Bus, spricht ISO-TP wie eine echte ECU und
beantwortet UDS-Anfragen gemäß ladbarer Simulations-Konfiguration: Sessions (inkl. S3-Rückfall),
Security Access (Seeds, Fehlversuchssperre, Zeitsperre), DIDs, DTCs, Routinen, Speicherzugriff,
Up-/Download, ResponsePending (0x78) und gezielte Fehlerinjektion (Overrides).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from ..can.channel import CanChannel
from ..core.hexutil import parse_hex, to_hex
from ..isotp.profile import IsoTpProfile
from ..isotp.transport import IsoTpTransport
from ..security.providers import SeedKeyProvider
from .models import SimEcuConfig, SimOverride

log = logging.getLogger("udsbench.app.sim")

#: NRCs, die bei funktionaler Adressierung nicht gesendet werden (ISO 14229-1 7.5)
FUNCTIONAL_SUPPRESSED_NRC = {0x11, 0x12, 0x31, 0x7E, 0x7F}


class Nrc(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"NRC 0x{code:02X}")
        self.code = code


def match_pattern(pattern: str, data: bytes) -> bool:
    """Hex-Muster mit '??' als Wildcard-Byte und optionalem '*' am Ende."""
    p = pattern.replace(",", " ").split()
    any_rest = bool(p) and p[-1] == "*"
    if any_rest:
        p = p[:-1]
    if len(p) > len(data) or (not any_rest and len(p) != len(data)):
        return False
    for tok, b in zip(p, data, strict=False):
        if tok == "??":
            continue
        if int(tok, 16) != b:
            return False
    return True


class SimulatedEcu:
    def __init__(
        self,
        cfg: SimEcuConfig,
        profile: IsoTpProfile,
        bus_name: str,
        provider_factory: Callable[[str, dict[str, Any]], SeedKeyProvider],
    ) -> None:
        self.cfg = cfg
        self.id = cfg.ecu
        self.channel_name = profile.channel
        self.provider_factory = provider_factory
        self.channel = CanChannel(f"sim:{cfg.ecu}", "virtual", {"bus": bus_name, "fd": True})
        self.profile = profile.mirrored(name=f"sim:{profile.name}")
        self.tp = IsoTpTransport(self.channel, self.profile, name=f"sim:{cfg.ecu}")
        self.ftp: IsoTpTransport | None = None
        if profile.functional_id is not None:
            fprof = self.profile.model_copy(update={"rx_address_extension": None})
            self.ftp = IsoTpTransport(
                self.channel, fprof, name=f"sim:{cfg.ecu}:func", rx_id=profile.functional_id
            )
        self._tasks: list[asyncio.Task[None]] = []
        self.reset_state(full=True)

    # Zustand --------------------------------------------------------------------------------
    def reset_state(self, full: bool = False) -> None:
        self.session = 0x01
        self.unlocked: set[int] = set()
        self.pending_seed: dict[int, bytes] = {}
        self.last_request = time.time()
        self.transfer: dict[str, Any] | None = None
        self.routines_started: set[int] = set()
        self.comm_control = 0x00
        self.dtc_setting = 0x01
        if full:
            self.dids: dict[int, bytearray] = {d.id: bytearray(parse_hex(d.value)) for d in self.cfg.dids}
            self.dtcs: dict[int, int] = {d.code: d.status for d in self.cfg.dtcs}
            self.memory = bytearray(self.cfg.memory_size)
            self.attempts: dict[int, int] = {}
            self.locked_until: dict[int, float] = {}
            self.override_counts: dict[int, int] = {}
            self.dyn_dids: dict[int, list[tuple[int, int, int]]] = {}
            self.requests = 0

    def state(self) -> dict[str, Any]:
        return {
            "ecu": self.id,
            "session": self.session,
            "unlocked": sorted(self.unlocked),
            "dids": {f"0x{k:04X}": to_hex(bytes(v)) for k, v in self.dids.items()},
            "dtcs": {f"{k:06X}": f"{v:02X}" for k, v in self.dtcs.items()},
            "locked_until": {k: v for k, v in self.locked_until.items() if v > time.time()},
            "attempts": self.attempts,
            "transfer": {k: v for k, v in (self.transfer or {}).items() if k != "data"}
            if self.transfer
            else None,
            "requests": self.requests,
            "comm_control": self.comm_control,
            "dtc_setting": self.dtc_setting,
        }

    # Lebenszyklus ---------------------------------------------------------------------------
    async def start(self) -> None:
        await self.channel.open()
        self.tp.start()
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._serve(self.tp, False)))
        if self.ftp:
            self.ftp.start()
            self._tasks.append(loop.create_task(self._serve(self.ftp, True)))
        log.info(
            "ECU-Testdouble %s gestartet (Rx 0x%X / Tx 0x%X)", self.id, self.profile.rx_id, self.profile.tx_id
        )

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()
        self.tp.stop()
        if self.ftp:
            self.ftp.stop()
        await self.channel.close()

    async def _serve(self, tr: IsoTpTransport, functional: bool) -> None:
        while True:
            msg = await tr.receive(None)
            try:
                await self._handle(msg.payload, functional)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                log.exception("Fehler im ECU-Testdouble")

    async def _send(self, payload: bytes) -> None:
        try:
            await self.tp.send(payload)
        except Exception as exc:
            log.warning("Testdouble %s: Senden fehlgeschlagen: %s", self.id, exc)

    # Verarbeitung ---------------------------------------------------------------------------
    async def _handle(self, req: bytes, functional: bool) -> None:
        self.requests += 1
        now = time.time()
        if self.session != 0x01 and (now - self.last_request) * 1000 > self.cfg.s3_server_ms:
            log.info("Testdouble %s: S3-Timeout → DefaultSession", self.id)
            self.session = 0x01
            self.unlocked.clear()
        self.last_request = now
        if not req:
            return
        ov = self._override(req)
        if ov is not None:
            for _ in range(ov.pending):
                await self._send(bytes([0x7F, req[0], 0x78]))
                await asyncio.sleep(max(ov.delay_ms, 10) / 1000)
            if ov.delay_ms and not ov.pending:
                await asyncio.sleep(ov.delay_ms / 1000)
            if ov.respond:
                await self._send(parse_hex(ov.respond))
            return
        if self.cfg.response_delay_ms:
            await asyncio.sleep(self.cfg.response_delay_ms / 1000)
        sid = req[0]
        try:
            if self.cfg.services is not None and sid not in self.cfg.services:
                raise Nrc(0x11)
            if sid in self.cfg.service_sessions and self.session not in self.cfg.service_sessions[sid]:
                raise Nrc(0x7F)
            handler = getattr(self, f"_svc_{sid:02x}", None)
            if handler is None:
                raise Nrc(0x11)
            result = await handler(req)
        except Nrc as n:
            if functional and n.code in FUNCTIONAL_SUPPRESSED_NRC:
                return
            await self._send(bytes([0x7F, sid, n.code]))
            return
        if result is None:
            return
        # SPRMIB: positive Antwort unterdrücken
        if (
            len(req) >= 2
            and sid in (0x10, 0x11, 0x27, 0x28, 0x29, 0x2C, 0x31, 0x3E, 0x83, 0x85, 0x86, 0x87)
            and req[1] & 0x80
        ):
            return
        await self._send(result)

    def _override(self, req: bytes) -> SimOverride | None:
        for idx, ov in enumerate(self.cfg.overrides):
            if match_pattern(ov.match, req):
                used = self.override_counts.get(idx, 0)
                if ov.times is not None and used >= ov.times:
                    continue
                self.override_counts[idx] = used + 1
                return ov
        return None

    def _sub(self, req: bytes, exact: int | None = None, minimum: int = 2) -> int:
        if len(req) < minimum or (exact is not None and len(req) != exact):
            raise Nrc(0x13)
        return req[1] & 0x7F

    # 0x10 DiagnosticSessionControl
    async def _svc_10(self, req: bytes) -> bytes:
        sub = self._sub(req, exact=2)
        if sub not in self.cfg.sessions:
            raise Nrc(0x12)
        if sub != self.session:
            self.unlocked.clear()
            self.pending_seed.clear()
        self.session = sub
        return (
            bytes([0x50, sub])
            + self.cfg.p2_server_max_ms.to_bytes(2, "big")
            + (self.cfg.p2_star_server_max_ms // 10).to_bytes(2, "big")
        )

    # 0x11 ECUReset
    async def _svc_11(self, req: bytes) -> bytes:
        sub = self._sub(req, exact=2)
        if sub not in (0x01, 0x02, 0x03, 0x04, 0x05):
            raise Nrc(0x12)
        if sub in (0x01, 0x02, 0x03):
            self.reset_state()
            return bytes([0x51, sub])
        return bytes([0x51, sub, 0x0F]) if sub == 0x04 else bytes([0x51, sub])

    # 0x3E TesterPresent
    async def _svc_3e(self, req: bytes) -> bytes:
        sub = self._sub(req, exact=2)
        if sub != 0x00:
            raise Nrc(0x12)
        return bytes([0x7E, 0x00])

    # 0x27 SecurityAccess
    async def _svc_27(self, req: bytes) -> bytes:
        sub = self._sub(req)
        lvl_seed = sub if sub % 2 else sub - 1
        lvl = next((s for s in self.cfg.security if s.level == lvl_seed), None)
        if lvl is None:
            raise Nrc(0x12)
        allowed = lvl.sessions if lvl.sessions is not None else [s for s in self.cfg.sessions if s != 0x01]
        if self.session not in allowed:
            raise Nrc(0x7F)
        now = time.time()
        if sub % 2:  # requestSeed
            if len(req) > 2:
                raise Nrc(0x31)  # securityAccessDataRecord wird vom Testdouble nicht unterstützt
            if self.locked_until.get(lvl_seed, 0) > now:
                raise Nrc(0x37)
            if lvl_seed in self.unlocked:
                return bytes([0x67, sub]) + bytes(lvl.seed_length)
            seed = parse_hex(lvl.static_seed) if lvl.static_seed else secrets.token_bytes(lvl.seed_length)
            if not any(seed):
                seed = b"\x01" + seed[1:]
            self.pending_seed[lvl_seed] = seed
            return bytes([0x67, sub]) + seed
        # sendKey
        if len(req) < 3:
            raise Nrc(0x13)
        if lvl_seed not in self.pending_seed:
            raise Nrc(0x24)
        seed = self.pending_seed.pop(lvl_seed)
        provider = self.provider_factory(lvl.provider, lvl.params)
        expected = provider.compute_key(seed, lvl_seed, provider.merged(lvl.params))
        key = req[2:]
        if len(key) != len(expected):
            raise Nrc(0x13)
        if key != expected:
            self.attempts[lvl_seed] = self.attempts.get(lvl_seed, 0) + 1
            if self.attempts[lvl_seed] >= lvl.max_attempts:
                self.locked_until[lvl_seed] = now + lvl.lockout_ms / 1000
                self.attempts[lvl_seed] = 0
                raise Nrc(0x36)
            raise Nrc(0x35)
        self.attempts[lvl_seed] = 0
        self.unlocked.add(lvl_seed)
        return bytes([0x67, sub])

    # 0x22 ReadDataByIdentifier
    def _did_value(self, did: int) -> bytes:
        if did in self.dyn_dids:
            out = b""
            for src, pos, size in self.dyn_dids[did]:
                out += self._did_value(src)[pos - 1 : pos - 1 + size]
            return out
        return bytes(self.dids[did])

    async def _svc_22(self, req: bytes) -> bytes:
        if len(req) < 3 or (len(req) - 1) % 2:
            raise Nrc(0x13)
        out = bytearray([0x62])
        any_ok = False
        for i in range(1, len(req), 2):
            did = int.from_bytes(req[i : i + 2], "big")
            spec = next((d for d in self.cfg.dids if d.id == did), None)
            if did not in self.dids and did not in self.dyn_dids:
                continue
            if spec and spec.sessions is not None and self.session not in spec.sessions:
                continue
            if spec and spec.read_security_level and spec.read_security_level not in self.unlocked:
                raise Nrc(0x33)
            out += req[i : i + 2] + self._did_value(did)
            any_ok = True
        if not any_ok:
            raise Nrc(0x31)
        return bytes(out)

    # 0x2E WriteDataByIdentifier
    async def _svc_2e(self, req: bytes) -> bytes:
        if len(req) < 4:
            raise Nrc(0x13)
        did = int.from_bytes(req[1:3], "big")
        spec = next((d for d in self.cfg.dids if d.id == did), None)
        if spec is None or not spec.writable:
            raise Nrc(0x31)
        if spec.sessions is not None and self.session not in spec.sessions:
            raise Nrc(0x31)
        if spec.security_level and spec.security_level not in self.unlocked:
            raise Nrc(0x33)
        data = req[3:]
        exp_len = spec.length if spec.length is not None else len(self.dids.get(did, b"")) or None
        if exp_len is not None and len(data) != exp_len:
            raise Nrc(0x13)
        self.dids[did] = bytearray(data)
        return bytes([0x6E]) + req[1:3]

    # 0x2F InputOutputControlByIdentifier
    async def _svc_2f(self, req: bytes) -> bytes:
        if len(req) < 4:
            raise Nrc(0x13)
        did = int.from_bytes(req[1:3], "big")
        if did not in self.dids:
            raise Nrc(0x31)
        param = req[3]
        if param > 0x03:
            raise Nrc(0x31)
        if param == 0x03:
            if len(req) < 5:
                raise Nrc(0x13)
            self.dids[did] = bytearray(req[4 : 4 + len(self.dids[did])] or req[4:])
        return bytes([0x6F]) + req[1:4] + bytes(self.dids[did])

    # 0x24 ReadScalingDataByIdentifier
    async def _svc_24(self, req: bytes) -> bytes:
        if len(req) != 3:
            raise Nrc(0x13)
        did = int.from_bytes(req[1:3], "big")
        if did not in self.dids:
            raise Nrc(0x31)
        return bytes([0x64]) + req[1:3] + bytes([0x01 << 4 | 0x01, 0x00])

    # 0x2C DynamicallyDefineDataIdentifier
    async def _svc_2c(self, req: bytes) -> bytes:
        sub = self._sub(req)
        if sub == 0x01:
            if len(req) < 8 or (len(req) - 4) % 4:
                raise Nrc(0x13)
            ddid = int.from_bytes(req[2:4], "big")
            items = []
            for i in range(4, len(req), 4):
                src = int.from_bytes(req[i : i + 2], "big")
                if src not in self.dids:
                    raise Nrc(0x31)
                items.append((src, req[i + 2], req[i + 3]))
            self.dyn_dids[ddid] = items
            return bytes([0x6C, sub]) + req[2:4]
        if sub == 0x03:
            if len(req) >= 4:
                self.dyn_dids.pop(int.from_bytes(req[2:4], "big"), None)
                return bytes([0x6C, sub]) + req[2:4]
            self.dyn_dids.clear()
            return bytes([0x6C, sub])
        raise Nrc(0x12)

    # 0x19 ReadDTCInformation
    async def _svc_19(self, req: bytes) -> bytes:
        sub = self._sub(req)
        avail = self.cfg.dtc_status_availability_mask
        exact = {0x01: 3, 0x02: 3, 0x04: 6, 0x06: 6, 0x0A: 2, 0x03: 2}
        if sub in exact and len(req) != exact[sub]:
            raise Nrc(0x13)
        if sub == 0x01:
            mask = req[2]
            n = sum(1 for s in self.dtcs.values() if s & mask & avail)
            return bytes([0x59, 0x01, avail, 0x01]) + n.to_bytes(2, "big")
        if sub == 0x02:
            mask = req[2]
            out = bytearray([0x59, 0x02, avail])
            for code, st in self.dtcs.items():
                if st & mask & avail:
                    out += code.to_bytes(3, "big") + bytes([st & avail])
            return bytes(out)
        if sub == 0x0A:
            out = bytearray([0x59, 0x0A, avail])
            for code, st in self.dtcs.items():
                out += code.to_bytes(3, "big") + bytes([st & avail])
            return bytes(out)
        if sub in (0x04, 0x06):
            code = int.from_bytes(req[2:5], "big")
            if code not in self.dtcs:
                raise Nrc(0x31)
            spec = next((d for d in self.cfg.dtcs if d.code == code), None)
            rec = parse_hex((spec.snapshot if sub == 0x04 else spec.extended) if spec else "")
            return bytes([0x59, sub]) + code.to_bytes(3, "big") + bytes([self.dtcs[code]]) + rec
        if sub == 0x03:
            out = bytearray([0x59, 0x03])
            for d in self.cfg.dtcs:
                if d.snapshot:
                    out += d.code.to_bytes(3, "big") + b"\x01"
            return bytes(out)
        raise Nrc(0x12)

    # 0x14 ClearDiagnosticInformation
    async def _svc_14(self, req: bytes) -> bytes:
        if len(req) not in (4, 5):
            raise Nrc(0x13)
        group = int.from_bytes(req[1:4], "big")
        if group == 0xFFFFFF:
            for code in self.dtcs:
                self.dtcs[code] = 0x50  # testNotCompletedSinceLastClear | testNotCompletedThisOperationCycle
        elif group in self.dtcs:
            self.dtcs[group] = 0x50
        else:
            raise Nrc(0x31)
        return bytes([0x54])

    # 0x31 RoutineControl
    async def _svc_31(self, req: bytes) -> bytes:
        sub = self._sub(req, minimum=4)
        rid = int.from_bytes(req[2:4], "big")
        r = next((x for x in self.cfg.routines if x.id == rid), None)
        if r is None:
            raise Nrc(0x31)
        if sub not in (0x01, 0x02, 0x03):
            raise Nrc(0x12)
        if r.sessions is not None and self.session not in r.sessions:
            raise Nrc(0x7F if self.session == 0x01 else 0x22)
        if r.security_level and r.security_level not in self.unlocked:
            raise Nrc(0x33)
        if sub in (0x02, 0x03) and r.requires_start and rid not in self.routines_started:
            raise Nrc(0x24)
        if sub == 0x01:
            self.routines_started.add(rid)
        elif sub == 0x02:
            self.routines_started.discard(rid)
        for _ in range(r.pending):
            await self._send(bytes([0x7F, 0x31, 0x78]))
            await asyncio.sleep(0.02)
        return bytes([0x71, req[1]]) + req[2:4] + parse_hex(r.result)

    # 0x28 CommunicationControl
    async def _svc_28(self, req: bytes) -> bytes:
        sub = self._sub(req, minimum=3)
        if sub not in (0x00, 0x01, 0x02, 0x03):
            raise Nrc(0x12)
        if len(req) != 3:
            raise Nrc(0x13)
        if req[2] not in (0x01, 0x02, 0x03):
            raise Nrc(0x31)
        self.comm_control = sub
        return bytes([0x68, sub])

    # 0x85 ControlDTCSetting
    async def _svc_85(self, req: bytes) -> bytes:
        sub = self._sub(req)
        if sub not in (0x01, 0x02):
            raise Nrc(0x12)
        self.dtc_setting = sub
        return bytes([0xC5, sub])

    # Speicher
    def _addr(self, alfid: int, data: bytes) -> tuple[int, int]:
        a_len, s_len = alfid & 0x0F, alfid >> 4
        if not a_len or not s_len or len(data) < a_len + s_len:
            raise Nrc(0x13 if len(data) < a_len + s_len else 0x31)
        addr = int.from_bytes(data[:a_len], "big")
        size = int.from_bytes(data[a_len : a_len + s_len], "big")
        if size == 0 or addr + size > len(self.memory):
            raise Nrc(0x31)
        return addr, size

    async def _svc_23(self, req: bytes) -> bytes:
        if len(req) < 4:
            raise Nrc(0x13)
        addr, size = self._addr(req[1], req[2:])
        return bytes([0x63]) + bytes(self.memory[addr : addr + size])

    async def _svc_3d(self, req: bytes) -> bytes:
        if len(req) < 5:
            raise Nrc(0x13)
        alfid = req[1]
        n = (alfid & 0x0F) + (alfid >> 4)
        addr, size = self._addr(alfid, req[2:])
        data = req[2 + n :]
        if len(data) != size:
            raise Nrc(0x13)
        self.memory[addr : addr + size] = data
        return bytes([0x7D]) + req[1 : 2 + n]

    def _require_unlock(self) -> None:
        if self.cfg.security and not self.unlocked:
            raise Nrc(0x33)

    async def _svc_34(self, req: bytes) -> bytes:
        return await self._start_transfer(req, "download")

    async def _svc_35(self, req: bytes) -> bytes:
        return await self._start_transfer(req, "upload")

    async def _start_transfer(self, req: bytes, direction: str) -> bytes:
        if len(req) < 5:
            raise Nrc(0x13)
        self._require_unlock()
        if self.transfer is not None:
            raise Nrc(0x22)
        alfid = req[2]
        if len(req) != 3 + (alfid & 0x0F) + (alfid >> 4):
            raise Nrc(0x13)
        addr, size = self._addr(alfid, req[3:])
        self.transfer = {
            "direction": direction,
            "address": addr,
            "size": size,
            "pos": 0,
            "counter": 1,
            "last": None,
        }
        mbl = self.cfg.max_block_length
        return bytes([0x74 if direction == "download" else 0x75, 0x20]) + mbl.to_bytes(2, "big")

    async def _svc_36(self, req: bytes) -> bytes:
        if len(req) < 2:
            raise Nrc(0x13)
        t = self.transfer
        if t is None:
            raise Nrc(0x24)
        bsc = req[1]
        if bsc == t["last"] and bsc != t["counter"]:
            # Wiederholung des letzten Blocks → positiv bestätigen (ISO 14229-1)
            return bytes([0x76, bsc])
        if bsc != t["counter"]:
            raise Nrc(0x73)
        mbl = self.cfg.max_block_length
        if t["direction"] == "download":
            data = req[2:]
            if len(data) + 2 > mbl or t["pos"] + len(data) > t["size"]:
                raise Nrc(0x13 if len(data) + 2 > mbl else 0x71)
            a = t["address"] + t["pos"]
            self.memory[a : a + len(data)] = data
            t["pos"] += len(data)
            resp = bytes([0x76, bsc])
        else:
            n = min(mbl - 2, t["size"] - t["pos"])
            if n <= 0:
                raise Nrc(0x24)
            a = t["address"] + t["pos"]
            t["pos"] += n
            resp = bytes([0x76, bsc]) + bytes(self.memory[a : a + n])
        t["last"] = bsc
        t["counter"] = (bsc + 1) & 0xFF
        return resp

    async def _svc_37(self, req: bytes) -> bytes:
        if self.transfer is None:
            raise Nrc(0x24)
        if self.transfer["direction"] == "download" and self.transfer["pos"] != self.transfer["size"]:
            self.transfer = None
            raise Nrc(0x72)
        self.transfer = None
        return bytes([0x77])

    # Weitere Dienste (vereinfacht)
    async def _svc_2a(self, req: bytes) -> bytes:
        if len(req) < 2:
            raise Nrc(0x13)
        if req[1] not in (0x01, 0x02, 0x03, 0x04):
            raise Nrc(0x31)
        return bytes([0x6A])

    async def _svc_83(self, req: bytes) -> bytes:
        sub = self._sub(req)
        if sub in (0x01, 0x03):
            return (
                bytes([0xC3, sub])
                + self.cfg.p2_server_max_ms.to_bytes(2, "big")
                + (self.cfg.p2_star_server_max_ms // 10).to_bytes(2, "big")
            )
        if sub in (0x02, 0x04):
            return bytes([0xC3, sub])
        raise Nrc(0x12)

    async def _svc_86(self, req: bytes) -> bytes:
        if len(req) < 3:
            raise Nrc(0x13)
        sub = req[1] & 0x3F
        if sub > 0x09:
            raise Nrc(0x12)
        return bytes([0xC6, req[1] & 0x7F, 0x00, req[2]])

    async def _svc_87(self, req: bytes) -> bytes:
        sub = self._sub(req)
        exact = {0x01: 3, 0x02: 5, 0x03: 2}
        if sub not in exact:
            raise Nrc(0x12)
        if len(req) != exact[sub]:
            raise Nrc(0x13)
        return bytes([0xC7, sub])
