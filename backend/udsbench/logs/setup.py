"""Strukturiertes Logging: JSON-Lines-Dateien je Kanal, Konsole, Ringpuffer, Maskierung.

Kanäle (Logger-Namen):
  * ``udsbench.app``   – Anwendungs-Log
  * ``udsbench.comm``  – Kommunikations-Log (jede UDS-Request/Response mit Timing)
  * ``udsbench.audit`` – Audit-Log (sicherheitsrelevante Aktionen)
  * ``udsbench.test``  – Test-Log (je Schritt)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.context import current

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
CHANNELS = ("app", "comm", "audit", "test")

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {"message", "asctime"}


class Masker:
    def __init__(self, enabled: bool, fields: list[str]) -> None:
        self.enabled = enabled
        self.fields = [f.lower() for f in fields]
        self._re = (
            re.compile(
                r"(?i)\b("
                + "|".join(re.escape(f) for f in self.fields)
                + r")\b(\s*[=:]\s*)([0-9A-Fa-f ]{2,}|\S+)"
            )
            if self.fields
            else None
        )

    def is_secret(self, key: str) -> bool:
        k = key.lower()
        return any(f in k for f in self.fields)

    def mask_value(self, key: str, value: Any) -> Any:
        if not self.enabled:
            return value
        if self.is_secret(key):
            return "***"
        if isinstance(value, dict):
            return {k: self.mask_value(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.mask_value(key, v) for v in value]
        return value

    def mask_text(self, text: str) -> str:
        if not self.enabled or not self._re:
            return text
        return self._re.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


_masker = Masker(True, ["seed", "key", "password", "token", "secret"])


def get_masker() -> Masker:
    return _masker


def record_to_dict(record: logging.LogRecord) -> dict[str, Any]:
    d: dict[str, Any] = {
        "ts": record.created,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
        + f".{int(record.msecs):03d}",
        "level": record.levelname,
        "channel": _channel(record.name),
        "logger": record.name,
        "msg": _masker.mask_text(record.getMessage()),
        "cid": getattr(record, "cid", None),
    }
    for k, v in record.__dict__.items():
        if k not in _RESERVED and k not in d and not k.startswith("_"):
            d[k] = _masker.mask_value(k, v)
    if record.exc_info:
        d["exc"] = logging.Formatter().formatException(record.exc_info)
    return d


def _channel(name: str) -> str:
    parts = name.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in CHANNELS else "app"


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "cid", None):
            record.cid = current()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_to_dict(record), ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        t = time.strftime("%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}"
        cid = getattr(record, "cid", None)
        base = f"{t} {record.levelname:<7} [{_channel(record.name)}] {_masker.mask_text(record.getMessage())}"
        if cid:
            base += f"  (cid={cid})"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class ChannelFilter(logging.Filter):
    def __init__(self, channel: str) -> None:
        super().__init__()
        self.channel = channel

    def filter(self, record: logging.LogRecord) -> bool:
        return _channel(record.name) == self.channel


class BufferHandler(logging.Handler):
    """Ringpuffer für die API + Push an Abonnenten (WebSocket/SSE)."""

    def __init__(self, size: int) -> None:
        super().__init__()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=size)
        self.subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self.seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            d = record_to_dict(record)
        except Exception:  # pragma: no cover
            return
        with self._lock:
            self.seq += 1
            d["seq"] = self.seq
            self.buffer.append(d)
        for fn in list(self.subscribers):
            try:
                fn(d)
            except Exception:  # pragma: no cover
                pass

    def query(
        self,
        channel: str | None = None,
        level: str | None = None,
        cid: str | None = None,
        since_seq: int = 0,
        limit: int = 500,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        min_level = logging.getLevelName(level) if level else 0
        out = []
        with self._lock:
            items = list(self.buffer)
        for d in items:
            if d["seq"] <= since_seq:
                continue
            if channel and d["channel"] != channel:
                continue
            if level and logging.getLevelName(d["level"]) < min_level:
                continue
            if cid and d.get("cid") != cid and d.get("run_id") != cid:
                continue
            if text and text.lower() not in d["msg"].lower():
                continue
            out.append(d)
        return out[-limit:]


_buffer: BufferHandler | None = None


def get_buffer() -> BufferHandler:
    global _buffer
    if _buffer is None:
        _buffer = BufferHandler(5000)
    return _buffer


def setup_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    *,
    console: bool = True,
    json_files: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backups: int = 5,
    buffer_size: int = 5000,
    mask_secrets: bool = True,
    mask_fields: list[str] | None = None,
) -> None:
    global _masker, _buffer
    _masker = Masker(mask_secrets, mask_fields or ["seed", "key", "password", "token", "secret"])
    root = logging.getLogger("udsbench")
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    lvl = TRACE if level == "TRACE" else getattr(logging, level, logging.INFO)
    root.setLevel(lvl)
    root.propagate = False
    cf = CorrelationFilter()
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(ConsoleFormatter())
        ch.addFilter(cf)
        ch.addFilter(lambda r: _channel(r.name) != "comm" or r.levelno >= logging.INFO)
        root.addHandler(ch)
    if json_files and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        for chn in CHANNELS:
            fh = logging.handlers.RotatingFileHandler(
                log_dir / f"{chn}.jsonl", maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            fh.setFormatter(JsonFormatter())
            fh.addFilter(cf)
            fh.addFilter(ChannelFilter(chn))
            root.addHandler(fh)
    _buffer = BufferHandler(buffer_size) if _buffer is None else _buffer
    _buffer.buffer = deque(_buffer.buffer, maxlen=buffer_size)
    _buffer.addFilter(cf)
    root.addHandler(_buffer)


def mask_uds(payload: bytes | None) -> str:
    """Hex-Darstellung einer UDS-Nachricht; Seeds/Keys (0x27/0x67) werden bei aktiver Maskierung verborgen."""
    if payload is None:
        return ""
    h = payload.hex(" ").upper()
    if _masker.enabled and len(payload) > 2 and payload[0] in (0x27, 0x67, 0x29, 0x69):
        return payload[:2].hex(" ").upper() + " ***"
    return h
