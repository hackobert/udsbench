"""Ausführungs-Engine für vordefinierte Botschaften, Sequenzen/Makros und Testschritte."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..can.frame import CanFrame
from ..core.errors import NotFoundError, UdsBenchError
from ..core.hexutil import parse_hex, parse_int, to_hex
from ..testrunner.assertions import AssertionResult, check_expect
from ..uds.client import UdsResult
from ..uds.codec import is_suppress_positive
from .expr import ExprError, Ns, evaluate, render_payload, render_template, resolve_value
from .models import Expect, Step

if TYPE_CHECKING:
    from ..core.diag import EcuRuntime
    from ..core.platform import Platform

log = logging.getLogger("udsbench.test.engine")


class ResultView:
    """Sicht auf ein UDS-Ergebnis für Ausdrücke (response, data, nrc, …)."""

    def __init__(self, res: UdsResult | None) -> None:
        self.res = res

    def expr_fields(self) -> dict[str, Any]:
        r = self.res
        if r is None:
            return {
                "response": b"",
                "data": b"",
                "nrc": None,
                "positive": False,
                "negative": False,
                "elapsed_ms": None,
                "pending": 0,
                "decoded": {},
                "timeout": True,
                "responses": [],
                "request": b"",
            }
        return {
            "response": r.response or b"",
            "data": r.data,
            "nrc": r.nrc,
            "positive": r.positive,
            "negative": r.negative,
            "elapsed_ms": r.elapsed_ms,
            "pending": r.pending_count,
            "decoded": r.decoded,
            "timeout": r.response is None,
            "responses": [x.payload for x in r.responses],
            "request": r.request,
        }


@dataclass
class StepRecord:
    name: str
    action: str
    depth: int = 0
    status: str = "passed"  # passed | failed | error | skipped
    started: float = 0.0
    duration_ms: float = 0.0
    ecu: str | None = None
    request: str | None = None
    response: str | None = None
    elapsed_ms: float | None = None
    nrc: int | None = None
    decoded: dict[str, Any] | None = None
    assertions: list[AssertionResult] = field(default_factory=list)
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    pending: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "depth": self.depth,
            "status": self.status,
            "started": self.started,
            "duration_ms": round(self.duration_ms, 3),
            "ecu": self.ecu,
            "request": self.request,
            "response": self.response,
            "elapsed_ms": self.elapsed_ms,
            "nrc": self.nrc,
            "decoded": self.decoded,
            "assertions": [a.to_dict() for a in self.assertions],
            "message": self.message,
            "details": self.details,
            "attempt": self.attempt,
        }


class Cancelled(Exception):
    pass


@dataclass
class ExecContext:
    platform: Platform
    vars: dict[str, Any] = field(default_factory=dict)
    ecu: str | None = None
    records: list[StepRecord] = field(default_factory=list)
    last: UdsResult | None = None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    on_record: Callable[[StepRecord], None] | None = None
    cid: str | None = None
    call_depth: int = 0
    log_lines: list[str] = field(default_factory=list)

    def env(self) -> dict[str, Any]:
        env: dict[str, Any] = {}
        env.update(self.vars)
        env["vars"] = Ns(self.vars)
        lv = ResultView(self.last).expr_fields()
        env.update(lv)
        env["last"] = Ns(lv)
        ecu_ns = Ns()
        try:
            rdef = self.platform.packages.merged.ecus.get(self.ecu or "")
            if rdef:
                p = rdef.profile
                ecu_ns.update(
                    {
                        "id": rdef.ecu.id,
                        "name": rdef.ecu.name,
                        "tx_id": p.tx_id,
                        "rx_id": p.rx_id,
                        "functional_id": p.functional_id,
                        **rdef.ecu.vars,
                    }
                )
        except Exception:  # pragma: no cover
            pass
        env["ecu"] = ecu_ns
        return env


DEFAULT_POSITIVE = Expect(positive=True)


class Engine:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform

    # ------------------------------------------------------------------------------------
    def runtime(self, ctx: ExecContext, step: Step | None = None, ecu: str | None = None) -> EcuRuntime:
        return self.platform.diag.get(ecu or (step.ecu if step else None) or ctx.ecu)

    async def run_steps(self, steps: list[Step], ctx: ExecContext, depth: int = 0) -> bool:
        ok = True
        for step in steps:
            if ctx.cancel.is_set():
                raise Cancelled()
            rec_ok = await self.run_step(step, ctx, depth)
            if not rec_ok:
                ok = False
                if not step.continue_on_failure:
                    return False
        return ok

    async def run_step(self, step: Step, ctx: ExecContext, depth: int = 0) -> bool:
        attempts = max(1, step.retries + 1)
        rec: StepRecord | None = None
        for attempt in range(1, attempts + 1):
            rec = StepRecord(
                step.label(),
                step.action,
                depth,
                started=time.time(),
                ecu=step.ecu or ctx.ecu,
                attempt=attempt,
            )
            t0 = time.perf_counter()
            try:
                await self._dispatch(step, ctx, rec, depth)
                self._finish(step, ctx, rec)
                if rec.status == "passed" and any(not a.ok for a in rec.assertions):
                    rec.status = "failed"
                    rec.message = rec.message or "; ".join(
                        f"{a.name}: {a.message}" for a in rec.assertions if not a.ok
                    )
            except Cancelled:
                rec.status = "error"
                rec.message = "abgebrochen"
                rec.duration_ms = (time.perf_counter() - t0) * 1000
                self._emit(ctx, rec)
                raise
            except (UdsBenchError, ExprError, ValueError, KeyError) as exc:
                rec.status = "error"
                rec.message = getattr(exc, "message", None) or str(exc)
            except Exception as exc:  # pragma: no cover - defensiv
                log.exception("Unerwarteter Fehler in Schritt %s", rec.name)
                rec.status = "error"
                rec.message = f"{type(exc).__name__}: {exc}"
            rec.duration_ms = (time.perf_counter() - t0) * 1000
            if rec.status == "passed" or attempt == attempts:
                break
            rec.details["retry_reason"] = rec.message
            self._emit(ctx, rec)
        assert rec is not None
        self._emit(ctx, rec)
        return rec.status in ("passed", "skipped")

    def _emit(self, ctx: ExecContext, rec: StepRecord) -> None:
        ctx.records.append(rec)
        level = logging.INFO if rec.status in ("passed", "skipped") else logging.WARNING
        log.log(
            level,
            "%s%s [%s] %s %s",
            "  " * rec.depth,
            rec.name,
            rec.status.upper(),
            f"{rec.request or ''} → {rec.response or '-'}" if rec.request else "",
            rec.message,
            extra={"step": rec.name, "status": rec.status, "action": rec.action},
        )
        if ctx.on_record:
            ctx.on_record(rec)

    # ------------------------------------------------------------------------------------
    async def _request(
        self,
        ctx: ExecContext,
        rec: StepRecord,
        step: Step,
        payload: bytes,
        *,
        functional: bool = False,
        expect: Expect | None = None,
        ecu: str | None = None,
        validate: str | None = None,
    ) -> UdsResult:
        rt = self.runtime(ctx, step, ecu)
        rec.ecu = rt.id
        res = await rt.request(payload, functional=functional, timeout_ms=step.timeout_ms, validate=validate)
        ctx.last = res
        rec.request = to_hex(payload)
        rec.response = to_hex(res.response) if res.response is not None else None
        rec.elapsed_ms = res.elapsed_ms
        rec.nrc = res.nrc
        rec.decoded = res.decoded
        if res.responses and functional:
            rec.details["responses"] = [r.to_dict() for r in res.responses]
        if res.error:
            rec.details["error"] = res.error
        # Assertions/Save werden erst nach der aktionsspezifischen Nachbearbeitung ausgewertet (run_step)
        rec.pending = (
            step.expect if step.expect is not None else (expect if expect is not None else DEFAULT_POSITIVE),
            res,
        )
        return res

    def _finish(self, step: Step, ctx: ExecContext, rec: StepRecord) -> None:
        if rec.pending is not None:
            exp, res = rec.pending
            rec.pending = None
            if step.save:
                env = ctx.env()
                for k, e in step.save.items():
                    try:
                        ctx.vars[k] = evaluate(e, env)
                    except ExprError as exc:
                        rec.assertions.append(AssertionResult(f"save:{k}", False, str(exc)))
            rec.assertions += check_expect(exp, res, ctx.env(), ctx)

    async def _dispatch(self, step: Step, ctx: ExecContext, rec: StepRecord, depth: int) -> None:
        a = step.action
        if a == "send":
            assert step.send is not None
            s = step.send
            env = ctx.env()
            expect = None
            ecu = step.ecu
            functional = s.functional
            if s.message:
                msg = self.platform.packages.merged.messages.get(s.message)
                if msg is None:
                    raise NotFoundError(f"Botschaft {s.message!r} nicht gefunden")
                env.update({k: resolve_value(v, env) for k, v in msg.vars.items() if k not in ctx.vars})
                template = msg.payload
                expect = msg.expect
                ecu = ecu or msg.ecu
                functional = functional or msg.functional
                rec.details["message"] = msg.id
            else:
                template = s.payload or ""
            env.update({k: resolve_value(v, env) for k, v in s.vars.items()})
            payload = render_payload(template, env)
            if expect is None:
                # Default: irgendeine Antwort (positiv oder negativ) muss kommen; bei SPRMIB keine Prüfung
                expect = Expect() if is_suppress_positive(payload) else Expect(no_response=False)
            await self._request(
                ctx, rec, step, payload, functional=functional, expect=expect, ecu=ecu, validate="warn"
            )
            return
        if a == "raw":
            assert step.raw is not None
            r = step.raw
            channel = r.channel
            if channel is None:
                try:
                    channel = self.runtime(ctx, step).rdef.profile.channel
                except Exception:
                    channel = "default"
            ch = self.platform.connections.get(channel)
            data = render_payload(r.data, ctx.env())
            await ch.send(CanFrame(r.id, data, r.extended, r.fd))
            rec.request = f"{r.id:X}#{to_hex(data)}"
            return
        if a == "wait":
            assert step.wait is not None
            try:
                await asyncio.wait_for(ctx.cancel.wait(), step.wait / 1000.0)
                raise Cancelled()
            except TimeoutError:
                pass
            rec.details["ms"] = step.wait
            return
        if a == "set":
            assert step.set is not None
            env = ctx.env()
            for k, v in step.set.items():
                ctx.vars[k] = resolve_value(v, env)
                env[k] = ctx.vars[k]
            rec.details["vars"] = {k: _show(ctx.vars[k]) for k in step.set}
            return
        if a == "log":
            text = render_template(step.log or "", ctx.env())
            ctx.log_lines.append(text)
            rec.message = text
            return
        if a == "assert":
            exprs = [step.assert_] if isinstance(step.assert_, str) else list(step.assert_ or [])
            env = ctx.env()
            for e in exprs:
                try:
                    v = evaluate(e, env)
                    rec.assertions.append(AssertionResult(f"assert:{e}", bool(v), f"→ {v!r}"))
                except ExprError as exc:
                    rec.assertions.append(AssertionResult(f"assert:{e}", False, str(exc)))
            return
        if a == "session":
            rt = self.runtime(ctx, step)
            sid = rt.resolve_session(step.session)  # type: ignore[arg-type]
            await self._request(ctx, rec, step, bytes([0x10, sid]))
            return
        if a == "reset":
            await self._request(ctx, rec, step, bytes([0x11, step.reset or 0x01]))
            return
        if a == "tester_present":
            rt = self.runtime(ctx, step)
            rt.tp_enabled = bool(step.tester_present)
            rec.details["enabled"] = rt.tp_enabled
            return
        if a == "request_seed":
            lvl = int(step.request_seed or 1)
            res = await self._request(ctx, rec, step, bytes([0x27, lvl]))
            if res.positive:
                ctx.vars["seed"] = res.data[1:]
                ctx.vars["seed_level"] = lvl
            return
        if a == "compute_key":
            ck = step.compute_key
            assert ck is not None
            seed = evaluate(ck.seed, ctx.env())
            seed_b = seed if isinstance(seed, (bytes, bytearray)) else parse_hex(str(seed))
            key = await self.platform.security.compute_key(
                step.ecu or ctx.ecu, ck.level, bytes(seed_b), provider=ck.provider
            )
            ctx.vars[ck.save_as] = key
            rec.details["key_length"] = len(key)
            return
        if a == "send_key":
            sk = step.send_key
            assert sk is not None
            if sk.key:
                kv = evaluate(sk.key, ctx.env()) if not _looks_hex(sk.key) else parse_hex(sk.key)
                key = bytes(kv) if isinstance(kv, (bytes, bytearray)) else parse_hex(str(kv))
            else:
                seed = ctx.vars.get("seed")
                if seed is None:
                    raise ValueError("send_key: kein Seed vorhanden (vorher request_seed ausführen)")
                key = await self.platform.security.compute_key(step.ecu or ctx.ecu, sk.level, bytes(seed))
            await self._request(ctx, rec, step, bytes([0x27, sk.level + 1]) + bytes(key))
            return
        if a == "unlock":
            lvl = int(step.unlock or 1)
            rt = self.runtime(ctx, step)
            result = await self.platform.security.unlock(rt.id, lvl)
            ctx.last = result.get("_last")
            rec.ecu = rt.id
            rec.details = {k: v for k, v in result.items() if not k.startswith("_")}
            last = result.get("_last")
            if last is not None:
                rec.request = (
                    to_hex(last.request)
                    if not self.platform.security.mask
                    else to_hex(last.request[:2]) + " ***"
                )
                rec.response = to_hex(last.response) if last.response is not None else None
                rec.nrc = last.nrc
                rec.elapsed_ms = last.elapsed_ms
            exp = step.expect if step.expect is not None else Expect()
            rec.assertions.append(
                AssertionResult(
                    "unlock",
                    bool(result.get("unlocked")) or step.expect is not None,
                    result.get("message", ""),
                )
            )
            if step.expect is not None:
                rec.assertions += check_expect(exp, last, ctx.env(), ctx)
            return
        if a == "read_did":
            refs = step.read_did if isinstance(step.read_did, list) else [step.read_did]
            dids = [self._did_id(r) for r in refs]
            payload = bytes([0x22]) + b"".join(d.to_bytes(2, "big") for d in dids)
            res = await self._request(ctx, rec, step, payload)
            values = ctx.vars.setdefault("values", {})
            for r in (res.decoded.get("fields", {}) or {}).get("records", []):
                key = r.get("name") or r["did_hex"]
                values[key] = r.get("value", r.get("raw"))
            return
        if a == "write_did":
            w = step.write_did
            assert w is not None
            did = self._did_id(w.did)
            if w.raw is not None:
                data = render_payload(w.raw, ctx.env())
            else:
                d = self.platform.packages.merged.catalogs.did(did)
                if d is None:
                    raise NotFoundError(f"DID 0x{did:04X} nicht im Katalog – 'raw' verwenden")
                data = d.encode(resolve_value(w.value, ctx.env()))
            await self._request(ctx, rec, step, bytes([0x2E]) + did.to_bytes(2, "big") + data)
            return
        if a == "io_control":
            io = step.io_control
            assert io is not None
            did = self._did_id(io.did)
            if io.raw is not None:
                data = render_payload(io.raw, ctx.env())
            elif io.value is not None:
                d = self.platform.packages.merged.catalogs.did(did)
                spec = (d.io_control_spec or d) if d else None
                if spec is None:
                    raise NotFoundError(f"DID 0x{did:04X} nicht im Katalog – 'raw' verwenden")
                data = spec.encode(resolve_value(io.value, ctx.env()))
            else:
                data = b""
            await self._request(
                ctx, rec, step, bytes([0x2F]) + did.to_bytes(2, "big") + bytes([io.parameter]) + data
            )
            return
        if a == "routine":
            ra = step.routine
            assert ra is not None
            cat = self.platform.packages.merged.catalogs
            rdef = cat.find_routine(ra.id)
            rid = rdef.id if rdef else parse_int(ra.id)
            sub = {"start": 0x01, "stop": 0x02, "results": 0x03}[ra.action]
            if ra.raw is not None:
                opt = render_payload(ra.raw, ctx.env())
            elif rdef and ra.params:
                from ..catalogs.models import encode_fields

                fields = rdef.start_params if ra.action == "start" else rdef.stop_params
                opt = encode_fields(fields, {k: resolve_value(v, ctx.env()) for k, v in ra.params.items()})
            else:
                opt = b""
            await self._request(ctx, rec, step, bytes([0x31, sub]) + rid.to_bytes(2, "big") + opt)
            return
        if a == "read_dtc":
            rd = step.read_dtc
            assert rd is not None
            payload = bytes([0x19, rd.subfunction])
            if rd.extra:
                payload += render_payload(rd.extra, ctx.env())
            elif rd.subfunction in (0x01, 0x02, 0x0F, 0x11, 0x12, 0x13):
                payload += bytes([rd.mask])
            res = await self._request(ctx, rec, step, payload)
            fl = res.decoded.get("fields", {}) if res.decoded else {}
            if "dtcs" in fl:
                ctx.vars["dtcs"] = fl["dtcs"]
            if "dtc_count" in fl:
                ctx.vars["dtc_count"] = fl["dtc_count"]
            return
        if a == "clear_dtc":
            grp = int(step.clear_dtc if step.clear_dtc is not None else 0xFFFFFF)
            await self._request(ctx, rec, step, bytes([0x14]) + grp.to_bytes(3, "big"))
            return
        if a == "transfer":
            await self._transfer(step, ctx, rec)
            return
        if a == "sequence":
            sref = step.sequence
            assert sref is not None
            seq_id: str = sref if isinstance(sref, str) else sref.id
            svars: dict[str, Any] = {} if isinstance(sref, str) else sref.vars
            seq = self.platform.packages.merged.sequences.get(seq_id)
            if seq is None:
                raise NotFoundError(f"Sequenz {seq_id!r} nicht gefunden")
            if ctx.call_depth > 20:
                raise ValueError("Maximale Verschachtelungstiefe von Sequenzen überschritten")
            env = ctx.env()
            for k, v in seq.vars.items():
                ctx.vars.setdefault(k, resolve_value(v, env))
            for k, v in svars.items():
                ctx.vars[k] = resolve_value(v, ctx.env())
            prev_ecu = ctx.ecu
            ctx.ecu = step.ecu or seq.ecu or ctx.ecu
            ctx.call_depth += 1
            try:
                ok = await self.run_steps(seq.steps, ctx, depth + 1)
            finally:
                ctx.call_depth -= 1
                ctx.ecu = prev_ecu
            if not ok:
                rec.status = "failed"
                rec.message = f"Sequenz {seq_id!r} fehlgeschlagen"
            return
        if a == "if":
            cond = step.if_
            assert cond is not None
            v = bool(evaluate(cond.condition, ctx.env()))
            rec.details["condition"] = v
            branch = cond.then if v else cond.else_
            if branch and not await self.run_steps(branch, ctx, depth + 1):
                rec.status = "failed"
                rec.message = "Zweig fehlgeschlagen"
            return
        if a == "repeat":
            rp = step.repeat
            assert rp is not None
            n = 0
            for i in range(max(0, rp.count)):
                ctx.vars[rp.var] = i
                n += 1
                if not await self.run_steps(rp.steps, ctx, depth + 1):
                    rec.status = "failed"
                    rec.message = f"Iteration {i} fehlgeschlagen"
                    break
                if rp.until and evaluate(rp.until, ctx.env()):
                    break
            rec.details["iterations"] = n
            return
        raise ValueError(f"Unbekannte Aktion {a}")  # pragma: no cover

    def _did_id(self, ref: Any) -> int:
        d = self.platform.packages.merged.catalogs.find_did(ref)
        if d is not None:
            return d.id
        if isinstance(ref, int):
            return ref
        return parse_int(ref)

    async def _transfer(self, step: Step, ctx: ExecContext, rec: StepRecord) -> None:
        t = step.transfer
        assert t is not None
        a_len, s_len = t.alfid & 0x0F, t.alfid >> 4
        data = b""
        if t.direction == "download":
            if t.file:
                base = self.platform.data_dir
                p = (base / t.file).resolve()
                if base.resolve() not in p.parents:
                    raise ValueError("Datei muss im Datenverzeichnis liegen")
                data = Path(p).read_bytes()
            elif t.data is not None:
                v = resolve_value(t.data, ctx.env())
                data = bytes(v) if isinstance(v, (bytes, bytearray)) else parse_hex(str(v))
            size = t.size if t.size is not None else len(data)
        else:
            if t.size is None:
                raise ValueError("Upload benötigt 'size'")
            size = t.size
        sid = 0x34 if t.direction == "download" else 0x35
        req = (
            bytes([sid, t.data_format, t.alfid])
            + t.address.to_bytes(a_len, "big")
            + size.to_bytes(s_len, "big")
        )
        sub_ok: list[dict[str, Any]] = []
        expect_pos = Expect(positive=True)
        tmp = Step(name=rec.name, wait=0, ecu=step.ecu, timeout_ms=step.timeout_ms)
        res = await self._request(ctx, rec, tmp, req, expect=expect_pos)
        self._finish(tmp, ctx, rec)
        sub_ok.append({"request": to_hex(req[:3]) + " …", "response": rec.response})
        if not res.positive:
            rec.status = "failed"
            rec.message = "Request" + ("Download" if sid == 0x34 else "Upload") + " abgelehnt"
            return
        mbl = res.decoded.get("fields", {}).get("max_number_of_block_length") or 0x82
        block = (t.block_length or mbl) - 2
        if block <= 0:
            raise ValueError("Ungültige Blocklänge")
        counter = 1
        pos = 0
        uploaded = bytearray()
        blocks = 0
        while pos < size:
            if ctx.cancel.is_set():
                raise Cancelled()
            if t.direction == "download":
                chunk = data[pos : pos + block]
                r = await self.runtime(ctx, step).request(
                    bytes([0x36, counter]) + chunk, timeout_ms=step.timeout_ms
                )
                pos += len(chunk)
            else:
                r = await self.runtime(ctx, step).request(bytes([0x36, counter]), timeout_ms=step.timeout_ms)
                got = r.data[1:] if r.positive else b""
                uploaded += got
                pos += len(got) if got else size
            blocks += 1
            if not r.positive or r.data[:1] != bytes([counter]):
                rec.status = "failed"
                rec.message = f"TransferData Block {blocks} (BSC 0x{counter:02X}) fehlgeschlagen: {r.error or to_hex(r.response)}"
                rec.assertions.append(AssertionResult("transfer", False, rec.message))
                return
            counter = (counter + 1) & 0xFF
        r = await self.runtime(ctx, step).request(bytes([0x37]), timeout_ms=step.timeout_ms)
        ctx.last = r
        ok = r.positive
        rec.assertions.append(
            AssertionResult(
                "transfer",
                ok,
                f"{blocks} Blöcke à max. {block} Byte, Exit {'OK' if ok else to_hex(r.response) or r.error}",
            )
        )
        rec.details.update({"blocks": blocks, "block_size": block, "bytes": size, "direction": t.direction})
        ctx.vars[t.save_as] = (
            bytes(uploaded) if t.direction == "upload" else {"blocks": blocks, "bytes": size}
        )


def _looks_hex(s: str) -> bool:
    cleaned = s.replace(" ", "")
    return bool(cleaned) and all(c in "0123456789abcdefABCDEF" for c in cleaned) and len(cleaned) % 2 == 0


def _show(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return to_hex(bytes(v))
    return v
