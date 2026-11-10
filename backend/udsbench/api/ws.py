"""WebSocket-Endpunkte: Live-Trace (gedrosselt, filterbar) und Ereignisse."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.platform import Platform
from ..core.trace import TraceFilter
from .deps import ws_authorized

ws_router = APIRouter()


def _dumps(d: Any) -> str:
    return json.dumps(d, default=str, ensure_ascii=False)


@ws_router.websocket("/ws/trace")
async def ws_trace(ws: WebSocket) -> None:
    """Live-Frames inkl. Klassifizierung.

    Client → Server: ``{"action": "pause"|"resume"}``, ``{"action": "filter", "filter": {...}}``,
    ``{"action": "views", "views": ["frames", "messages"]}``.
    Server → Client: ``{"type": "batch", "frames": [...], "messages": [...], "dropped": n}``.
    """
    if not ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    p: Platform = ws.app.state.platform
    sub = p.trace.subscribe()
    flt = dict(ws.query_params)
    flt.pop("token", None)
    if flt:
        sub.filter = TraceFilter.from_dict(flt)
    interval = p.config.trace.ws_batch_ms / 1000.0
    max_batch = p.config.trace.ws_max_batch

    async def sender() -> None:
        while True:
            first = await sub.queue.get()
            await asyncio.sleep(interval)
            items = [first]
            while not sub.queue.empty() and len(items) < max_batch:
                items.append(sub.queue.get_nowait())
            dropped = sub.dropped
            # Überlast: Rest verwerfen und melden (Backend-seitige Drosselung)
            if sub.queue.qsize() > max_batch * 4:
                while not sub.queue.empty():
                    sub.queue.get_nowait()
                    dropped += 1
            sub.dropped = 0
            await ws.send_text(
                _dumps(
                    {
                        "type": "batch",
                        "frames": [i for i in items if i["kind"] == "frame"],
                        "messages": [i for i in items if i["kind"] == "message"],
                        "dropped": dropped,
                    }
                )
            )

    async def receiver() -> None:
        while True:
            msg = json.loads(await ws.receive_text())
            action = msg.get("action")
            if action == "pause":
                sub.paused = True
            elif action == "resume":
                sub.paused = False
            elif action == "filter":
                sub.filter = TraceFilter.from_dict(msg.get("filter") or {})
            elif action == "views":
                sub.views = set(msg.get("views") or ["frames", "messages"])
            await ws.send_text(_dumps({"type": "ack", "action": action, "paused": sub.paused}))

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:  # pragma: no cover
        pass
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        p.trace.unsubscribe(sub)


@ws_router.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    """Testlauf-Fortschritt, Verbindungs-/Session-/Security-Ereignisse, Log-Einträge."""
    if not ws_authorized(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    p: Platform = ws.app.state.platform
    topics = set(filter(None, (ws.query_params.get("topics") or "").split(",")))
    q = p.events.subscribe()
    await ws.send_text(_dumps({"topic": "hello", "info": p.info()}))

    async def sender() -> None:
        while True:
            evt = await q.get()
            if topics and evt["topic"] not in topics:
                continue
            await ws.send_text(_dumps(evt))

    async def receiver() -> None:
        while True:
            await ws.receive_text()

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        p.events.unsubscribe(q)
