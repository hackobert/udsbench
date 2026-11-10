"""Test-Runner: Einzeltests und Suiten, Setup/Teardown, Datensätze, Wiederholungen, Reports."""

from __future__ import annotations

import asyncio
import json
import logging
import platform as pyplatform
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import __version__
from ..config.loader import safe_name
from ..core.context import correlated, new_id
from ..core.errors import ConflictError, NotFoundError
from ..messages.engine import Cancelled, Engine, ExecContext, StepRecord
from ..messages.expr import resolve_value
from ..messages.models import SequenceDef
from .models import SuiteDef, TestDef
from .report import to_junit

if TYPE_CHECKING:
    from ..core.platform import Platform

log = logging.getLogger("udsbench.test.runner")


@dataclass
class TestCaseResult:
    id: str
    name: str
    ecu: str | None
    iteration: int = 1
    dataset: dict[str, Any] | None = None
    status: str = "passed"  # passed | failed | error | skipped
    started: float = 0.0
    duration_ms: float = 0.0
    message: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    expected_result: str = "pass"

    @property
    def label(self) -> str:
        suffix = ""
        if self.dataset:
            suffix += " [" + ", ".join(f"{k}={_fmt(v)}" for k, v in self.dataset.items()) + "]"
        if self.iteration > 1:
            suffix += f" #{self.iteration}"
        return self.name + suffix

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "ecu": self.ecu,
            "iteration": self.iteration,
            "dataset": {k: _fmt(v) for k, v in (self.dataset or {}).items()},
            "status": self.status,
            "started": self.started,
            "duration_ms": round(self.duration_ms, 3),
            "message": self.message,
            "expected_result": self.expected_result,
            "steps": [s.to_dict() for s in self.steps],
            "log": self.log,
        }


def _fmt(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return v.hex(" ").upper()
    return v


@dataclass
class Run:
    id: str
    kind: str  # test | suite | sequence | security_nrc
    target: str
    name: str
    status: str = "queued"  # queued | running | passed | failed | error | cancelled
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    tests: list[TestCaseResult] = field(default_factory=list)
    suite_steps: list[StepRecord] = field(default_factory=list)
    total_planned: int = 0
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    vars: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def summary(self) -> dict[str, int]:
        s = {"total": len(self.tests), "passed": 0, "failed": 0, "error": 0, "skipped": 0}
        for t in self.tests:
            s[t.status] = s.get(t.status, 0) + 1
        return s

    def to_dict(self, detail: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.id,
            "kind": self.kind,
            "target": self.target,
            "name": self.name,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "duration_ms": round(((self.finished or time.time()) - (self.started or self.created)) * 1000, 3)
            if self.started
            else 0,
            "summary": self.summary(),
            "planned": self.total_planned,
            "error": self.error,
        }
        if detail:
            d["environment"] = self.environment
            d["vars"] = {k: _fmt(v) for k, v in self.vars.items()}
            d["tests"] = [t.to_dict() for t in self.tests]
            d["suite_steps"] = [s.to_dict() for s in self.suite_steps]
        return d


class TestRunner:
    def __init__(self, platform: Platform, reports_dir: Path) -> None:
        self.platform = platform
        self.engine = Engine(platform)
        self.reports_dir = reports_dir
        self.runs: dict[str, Run] = {}
        self._lock = asyncio.Lock()

    # Öffentliche API ------------------------------------------------------------------------
    def start_test(self, test_id: str, vars: dict[str, Any] | None = None, ecu: str | None = None) -> Run:
        t = self.platform.packages.merged.tests.get(test_id)
        if t is None:
            raise NotFoundError(f"Test {test_id!r} nicht gefunden")
        return self._start("test", test_id, t.name or t.id, [t], None, vars, ecu)

    def start_suite(self, suite_id: str, vars: dict[str, Any] | None = None, ecu: str | None = None) -> Run:
        s = self.platform.packages.merged.testsuites.get(suite_id)
        if s is None:
            raise NotFoundError(f"Testsuite {suite_id!r} nicht gefunden")
        return self._start("suite", suite_id, s.name or s.id, self.suite_tests(s), s, vars, ecu)

    def start_adhoc(
        self,
        kind: str,
        target: str,
        name: str,
        tests: list[TestDef],
        vars: dict[str, Any] | None = None,
        ecu: str | None = None,
        suite: SuiteDef | None = None,
    ) -> Run:
        return self._start(kind, target, name, tests, suite, vars, ecu)

    def start_sequence(self, seq_id: str, vars: dict[str, Any] | None = None, ecu: str | None = None) -> Run:
        seq: SequenceDef | None = self.platform.packages.merged.sequences.get(seq_id)
        if seq is None:
            raise NotFoundError(f"Sequenz {seq_id!r} nicht gefunden")
        t = TestDef(
            id=f"sequence.{seq.id}",
            name=seq.name or seq.id,
            ecu=seq.ecu,
            vars=dict(seq.vars),
            steps=seq.steps,
        )
        return self._start("sequence", seq_id, seq.name or seq.id, [t], None, vars, ecu)

    def suite_tests(self, s: SuiteDef) -> list[TestDef]:
        merged = self.platform.packages.merged
        tests: list[TestDef] = []
        for tid in s.tests:
            if tid not in merged.tests:
                raise NotFoundError(f"Suite {s.id!r}: Test {tid!r} nicht gefunden")
            tests.append(merged.tests[tid])
        if s.tags:
            for t in merged.tests.values():
                if t not in tests and set(t.tags) & set(s.tags):
                    tests.append(t)
        return tests

    def get(self, run_id: str) -> Run:
        if run_id not in self.runs:
            loaded = self._load_report(run_id)
            if loaded is None:
                raise NotFoundError(f"Lauf {run_id!r} nicht gefunden")
            return loaded
        return self.runs[run_id]

    def cancel(self, run_id: str) -> None:
        run = self.get(run_id)
        if run.status not in ("queued", "running"):
            raise ConflictError("Lauf ist bereits beendet")
        run.cancel.set()

    def list_items(self) -> list[dict[str, Any]]:
        items = {r.id: r.to_dict(detail=False) for r in self.runs.values()}
        if self.reports_dir.is_dir():
            for f in sorted(self.reports_dir.glob("*.json"), reverse=True)[:200]:
                if f.stem not in items:
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        d.pop("tests", None)
                        d.pop("suite_steps", None)
                        d.pop("environment", None)
                        items[f.stem] = d
                    except Exception:  # pragma: no cover
                        continue
        return sorted(items.values(), key=lambda d: d.get("created") or 0, reverse=True)

    async def wait(self, run_id: str, timeout: float | None = None) -> Run:
        run = self.get(run_id)
        if run.task:
            await asyncio.wait_for(asyncio.shield(run.task), timeout)
        return run

    def report(self, run_id: str, fmt: str = "json") -> str:
        run = self.get(run_id)
        if fmt == "junit":
            return to_junit(run.to_dict())
        return json.dumps(run.to_dict(), indent=2, ensure_ascii=False, default=str)

    # Intern ---------------------------------------------------------------------------------
    def _environment(self) -> dict[str, Any]:
        p = self.platform
        return {
            "tool": "udsbench",
            "version": __version__,
            "python": pyplatform.python_version(),
            "platform": pyplatform.platform(),
            "machine": pyplatform.machine(),
            "packages": p.packages.active_hashes(),
            "connections": [
                {"name": n, "backend": s.backend, "simulate": s.simulate}
                for n, s in p.connections.specs.items()
            ],
            "timing_defaults": p.config.timing.model_dump(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def _start(
        self,
        kind: str,
        target: str,
        name: str,
        tests: list[TestDef],
        suite: SuiteDef | None,
        vars: dict[str, Any] | None,
        ecu: str | None,
    ) -> Run:
        run = Run(new_id("run_"), kind, target, name, vars=dict(vars or {}))
        run.total_planned = sum(max(1, len(t.datasets)) * t.repeat for t in tests)
        run.environment = self._environment()
        self.runs[run.id] = run
        run.task = asyncio.get_running_loop().create_task(self._execute(run, tests, suite, ecu))
        self.platform.events.publish(
            "run", state="queued", run_id=run.id, kind=kind, target=target, name=name
        )
        return run

    def _publish(self, run: Run, **extra: Any) -> None:
        self.platform.events.publish(
            "run", run_id=run.id, status=run.status, summary=run.summary(), planned=run.total_planned, **extra
        )

    async def _execute(self, run: Run, tests: list[TestDef], suite: SuiteDef | None, ecu: str | None) -> None:
        async with self._lock:
            with correlated(run.id):
                run.status = "running"
                run.started = time.time()
                self._publish(run, state="started")
                log.info(
                    "Lauf %s gestartet: %s %s (%d Testfälle)",
                    run.id,
                    run.kind,
                    run.target,
                    run.total_planned,
                    extra={"run_id": run.id},
                )
                base_vars = dict(suite.vars if suite else {})
                base_vars.update(run.vars)
                suite_ecu = ecu or (suite.ecu if suite else None)
                try:
                    ok = True
                    if suite and suite.setup:
                        ctx = self._ctx(run, base_vars, suite_ecu, run.suite_steps)
                        ok = await self.engine.run_steps(suite.setup, ctx)
                        base_vars.update(ctx.vars)
                        if not ok:
                            run.error = "Suite-Setup fehlgeschlagen"
                    if ok:
                        for t in tests:
                            if run.cancel.is_set():
                                raise Cancelled()
                            datasets = t.datasets or [{}]
                            for ds in datasets:
                                for it in range(1, t.repeat + 1):
                                    res = await self._run_test(
                                        run, t, base_vars, ds if t.datasets else None, it, suite_ecu
                                    )
                                    run.tests.append(res)
                                    self._publish(run, state="progress", test=res.id, test_status=res.status)
                            if (
                                suite
                                and suite.stop_on_failure
                                and any(x.status in ("failed", "error") for x in run.tests)
                            ):
                                log.warning("Suite abgebrochen (stop_on_failure)")
                                break
                    if suite and suite.teardown:
                        ctx = self._ctx(run, base_vars, suite_ecu, run.suite_steps)
                        await self.engine.run_steps(suite.teardown, ctx)
                    s = run.summary()
                    if run.error or s["error"]:
                        run.status = "error"
                    elif s["failed"]:
                        run.status = "failed"
                    else:
                        run.status = "passed"
                except Cancelled:
                    run.status = "cancelled"
                except Exception as exc:  # pragma: no cover
                    log.exception("Lauf %s abgebrochen", run.id)
                    run.status = "error"
                    run.error = str(exc)
                run.finished = time.time()
                self._save(run)
                log.info(
                    "Lauf %s beendet: %s %s",
                    run.id,
                    run.status.upper(),
                    run.summary(),
                    extra={"run_id": run.id},
                )
                self._publish(run, state="finished")

    def _ctx(self, run: Run, vars: dict[str, Any], ecu: str | None, sink: list[StepRecord]) -> ExecContext:
        ctx = ExecContext(self.platform, vars=dict(vars), ecu=ecu, cid=run.id)
        ctx.cancel = run.cancel

        def on_record(rec: StepRecord) -> None:
            sink.append(rec)
            self.platform.events.publish("run.step", run_id=run.id, step=rec.to_dict())

        ctx.on_record = on_record
        return ctx

    async def _run_test(
        self,
        run: Run,
        t: TestDef,
        base_vars: dict[str, Any],
        ds: dict[str, Any] | None,
        it: int,
        ecu: str | None,
    ) -> TestCaseResult:
        res = TestCaseResult(
            t.id, t.name or t.id, t.ecu or ecu, it, ds, started=time.time(), expected_result=t.expected_result
        )
        vars_ = dict(base_vars)
        ctx = self._ctx(run, vars_, t.ecu or ecu, res.steps)
        env = ctx.env()
        for k, v in t.vars.items():
            ctx.vars[k] = resolve_value(v, env)
        for k, v in (ds or {}).items():
            ctx.vars[k] = resolve_value(v, ctx.env())
        ctx.vars.update({k: v for k, v in run.vars.items()})
        t0 = time.perf_counter()
        log.info("Test %s gestartet", res.label, extra={"test": t.id, "run_id": run.id})

        async def body() -> None:
            if t.preconditions and not await self.engine.run_steps(t.preconditions, ctx):
                res.status = "error"
                res.message = "Vorbedingung nicht erfüllt"
                return
            if t.setup and not await self.engine.run_steps(t.setup, ctx):
                res.status = "error"
                res.message = "Setup fehlgeschlagen"
                return
            ok = True
            for step in t.steps:
                if run.cancel.is_set():
                    raise Cancelled()
                if not await self.engine.run_step(step, ctx):
                    ok = False
                    last = res.steps[-1] if res.steps else None
                    if last and last.status == "error":
                        res.status = "error"
                    elif res.status != "error":
                        res.status = "failed"
                    res.message = res.message or (
                        f"{last.name}: {last.message}" if last else "Schritt fehlgeschlagen"
                    )
                    if t.abort_on_failure and not step.continue_on_failure:
                        break
            if ok:
                res.status = "passed"

        try:
            if t.timeout_s:
                await asyncio.wait_for(body(), t.timeout_s)
            else:
                await body()
        except TimeoutError:
            res.status = "error"
            res.message = f"Test-Timeout nach {t.timeout_s}s"
        except Cancelled:
            res.status = "error"
            res.message = "abgebrochen"
            raise
        finally:
            if t.teardown:
                try:
                    td_ctx = self._ctx(run, ctx.vars, ctx.ecu, res.steps)
                    await self.engine.run_steps(t.teardown, td_ctx)
                    ctx.log_lines += td_ctx.log_lines
                except Exception as exc:  # pragma: no cover
                    res.log.append(f"Teardown-Fehler: {exc}")
            res.duration_ms = (time.perf_counter() - t0) * 1000
            res.log += ctx.log_lines
        if t.expected_result == "fail":
            res.status = (
                "passed" if res.status == "failed" else ("failed" if res.status == "passed" else res.status)
            )
            if res.status == "passed":
                res.message = "Negativtest: Fehlschlag wie erwartet"
        log.log(
            logging.INFO if res.status == "passed" else logging.WARNING,
            "Test %s: %s %s",
            res.label,
            res.status.upper(),
            res.message,
            extra={"test": t.id, "run_id": run.id, "status": res.status},
        )
        return res

    def _save(self, run: Run) -> None:
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            (self.reports_dir / f"{safe_name(run.id)}.json").write_text(
                json.dumps(run.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception as exc:  # pragma: no cover
            log.error("Report konnte nicht gespeichert werden: %s", exc)

    def _load_report(self, run_id: str) -> Run | None:
        try:
            p = self.reports_dir / f"{safe_name(run_id)}.json"
        except Exception:
            return None
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return _StoredRun(d)  # type: ignore[return-value]


class _StoredRun:
    """Schreibgeschützte Sicht auf einen gespeicherten Report."""

    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d
        self.id = d["run_id"]
        self.status = d["status"]
        self.task = None

    def to_dict(self, detail: bool = True) -> dict[str, Any]:
        return self._d
