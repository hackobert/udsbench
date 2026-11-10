"""Trace-Aufzeichnung & Replay (Zeitbasis bleibt erhalten)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..can.frame import CanFrame
from ..config.loader import safe_name
from ..core.context import new_id
from ..core.errors import ConflictError, NotFoundError
from .traceformats import export_frames, import_frames

if TYPE_CHECKING:
    from ..core.platform import Platform

log = logging.getLogger("udsbench.app.recorder")


class Recording:
    def __init__(self, rec_id: str, name: str, channels: list[str] | None) -> None:
        self.id = rec_id
        self.name = name
        self.channels = channels
        self.frames: list[CanFrame] = []
        self.started = time.time()
        self.stopped: float | None = None

    def on_frame(self, f: CanFrame) -> None:
        if self.channels and f.channel not in self.channels:
            return
        self.frames.append(f)


class RecorderService:
    def __init__(self, platform: Platform, directory: Path) -> None:
        self.platform = platform
        self.dir = directory
        self.active: Recording | None = None
        self.replays: dict[str, dict[str, Any]] = {}

    def _path(self, rec_id: str) -> Path:
        return self.dir / f"{safe_name(rec_id)}.jsonl"

    # Aufzeichnung ---------------------------------------------------------------------------
    def start(self, name: str | None = None, channels: list[str] | None = None) -> dict[str, Any]:
        if self.active:
            raise ConflictError("Es läuft bereits eine Aufzeichnung")
        rec = Recording(new_id("rec_"), name or time.strftime("Aufzeichnung %Y-%m-%d %H:%M:%S"), channels)
        self.active = rec
        self.platform.trace.frame_listeners.append(rec.on_frame)
        self.platform.events.publish("recording", state="started", id=rec.id, name=rec.name)
        log.info("Aufzeichnung %s gestartet", rec.id)
        return {"id": rec.id, "name": rec.name, "started": rec.started}

    def stop(self) -> dict[str, Any]:
        rec = self.active
        if not rec:
            raise ConflictError("Keine aktive Aufzeichnung")
        self.platform.trace.frame_listeners.remove(rec.on_frame)
        self.active = None
        rec.stopped = time.time()
        self.save(rec.id, rec.name, rec.frames, {"started": rec.started, "stopped": rec.stopped})
        self.platform.events.publish("recording", state="stopped", id=rec.id, frames=len(rec.frames))
        log.info("Aufzeichnung %s gespeichert (%d Frames)", rec.id, len(rec.frames))
        return {"id": rec.id, "name": rec.name, "frames": len(rec.frames)}

    def save(
        self, rec_id: str, name: str, frames: list[CanFrame], extra: dict[str, Any] | None = None
    ) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "id": rec_id,
            "name": name,
            "frames": len(frames),
            "packages": self.platform.packages.active_hashes(),
            **(extra or {}),
        }
        self._path(rec_id).write_text(export_frames(frames, "jsonl", meta), encoding="utf-8")

    def list_items(self) -> list[dict[str, Any]]:
        out = []
        if self.dir.is_dir():
            for f in sorted(self.dir.glob("*.jsonl")):
                try:
                    with f.open(encoding="utf-8") as fh:
                        head = json.loads(fh.readline() or "{}")
                except Exception:
                    head = {}
                out.append(
                    {
                        "id": f.stem,
                        "name": head.get("name", f.stem),
                        "frames": head.get("frames"),
                        "started": head.get("started"),
                        "size": f.stat().st_size,
                    }
                )
        if self.active:
            out.append(
                {
                    "id": self.active.id,
                    "name": self.active.name,
                    "frames": len(self.active.frames),
                    "recording": True,
                }
            )
        return out

    def load(self, rec_id: str) -> tuple[list[CanFrame], dict[str, Any]]:
        p = self._path(rec_id)
        if not p.exists():
            raise NotFoundError(f"Aufzeichnung {rec_id!r} nicht gefunden")
        return import_frames(p.read_text(encoding="utf-8"), "jsonl")

    def delete(self, rec_id: str) -> None:
        p = self._path(rec_id)
        if not p.exists():
            raise NotFoundError(f"Aufzeichnung {rec_id!r} nicht gefunden")
        p.unlink()

    def export(self, rec_id: str, fmt: str) -> str:
        frames, meta = self.load(rec_id)
        return export_frames(
            frames, fmt, {k: v for k, v in meta.items() if k not in ("type", "format", "version", "t0")}
        )

    def import_text(self, text: str, name: str, fmt: str | None = None, filename: str = "") -> dict[str, Any]:
        frames, _ = import_frames(text, fmt, filename)
        rec_id = new_id("rec_")
        self.save(rec_id, name, frames, {"imported": filename or True})
        return {"id": rec_id, "name": name, "frames": len(frames)}

    # Replay ---------------------------------------------------------------------------------
    async def replay(
        self,
        rec_id: str,
        *,
        mode: str = "bus",
        channel: str | None = None,
        speed: float = 1.0,
        directions: list[str] | None = None,
        loop_count: int = 1,
    ) -> dict[str, Any]:
        frames, _ = self.load(rec_id)
        directions = directions or (["tx"] if mode == "bus" else ["tx", "rx"])
        sel = [f for f in frames if f.direction in directions]
        rid = new_id("replay_")
        info: dict[str, Any] = {
            "id": rid,
            "recording": rec_id,
            "mode": mode,
            "frames": len(sel),
            "sent": 0,
            "state": "running",
        }
        self.replays[rid] = info
        task = asyncio.get_running_loop().create_task(
            self._run_replay(info, sel, mode, channel, speed, loop_count)
        )
        info["_task"] = task
        return {k: v for k, v in info.items() if not k.startswith("_")}

    async def _run_replay(
        self,
        info: dict[str, Any],
        frames: list[CanFrame],
        mode: str,
        channel: str | None,
        speed: float,
        loop_count: int,
    ) -> None:
        try:
            for _ in range(max(1, loop_count)):
                if not frames:
                    break
                t0 = frames[0].timestamp
                start = time.perf_counter()
                for f in frames:
                    due = (f.timestamp - t0) / max(speed, 1e-6)
                    delay = due - (time.perf_counter() - start)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    fr = CanFrame(
                        f.arbitration_id,
                        f.data,
                        f.is_extended_id,
                        f.is_fd,
                        f.bitrate_switch,
                        direction=f.direction,
                        channel=channel or f.channel,
                    )
                    if mode == "bus":
                        ch = self.platform.connections.get(channel or f.channel)
                        await ch.send(fr)
                    else:
                        fr.timestamp = time.time()
                        self.platform.trace.on_frame(fr)
                    info["sent"] += 1
            info["state"] = "finished"
        except asyncio.CancelledError:
            info["state"] = "cancelled"
        except Exception as exc:
            info["state"] = "error"
            info["error"] = str(exc)
            log.error("Replay fehlgeschlagen: %s", exc)
        self.platform.events.publish("replay", **{k: v for k, v in info.items() if not k.startswith("_")})

    def cancel_replay(self, rid: str) -> None:
        info = self.replays.get(rid)
        if not info:
            raise NotFoundError(f"Replay {rid!r} nicht gefunden")
        t = info.get("_task")
        if t and not t.done():
            t.cancel()

    def replay_status(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in i.items() if not k.startswith("_")} for i in self.replays.values()]
