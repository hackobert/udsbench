"""DBC-Dateien verwalten, Kanälen zuordnen und Frames dekodieren/kodieren (über cantools).

Ablage im Datenverzeichnis: ``data/dbc/<id>.dbc`` und ``data/dbc/channels.json``
(Kanalname → Liste von DBC-IDs). Pro Kanal können mehrere DBCs aktiv sein; definieren zwei davon
dieselbe CAN-ID, gewinnt die zuerst zugeordnete Datei (wird als Konflikt gemeldet).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..can.frame import CanFrame
from ..core.errors import NotFoundError, ValidationFailed

log = logging.getLogger("udsbench.app.dbc")

MAX_DBC_BYTES = 20 * 1024 * 1024


def _slug(name: str) -> str:
    stem = re.sub(r"\.dbc$", "", name.strip(), flags=re.I)
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._-")
    return s[:80] or "dbc"


def _value(v: Any) -> Any:
    """cantools-Werte JSON-tauglich machen (NamedSignalValue → Name, bytes → Hex)."""
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if isinstance(v, (bytes, bytearray)):
        return v.hex(" ").upper()
    name = getattr(v, "name", None)
    if name is not None:
        return str(name)
    return str(v)


@dataclass
class DbcFile:
    id: str
    name: str
    path: Path
    db: Any  # cantools.database.can.Database
    added: float
    size: int

    def summary(self) -> dict[str, Any]:
        msgs = self.db.messages
        return {
            "id": self.id,
            "name": self.name,
            "messages": len(msgs),
            "signals": sum(len(m.signals) for m in msgs),
            "added": self.added,
            "size": self.size,
        }


@dataclass
class LiveEntry:
    message: str
    dbc: str
    frame_id: int
    extended: bool
    signals: dict[str, Any]
    units: dict[str, str]
    data: str
    ts: float
    count: int = 1
    dir: str = "rx"
    period_ms: float | None = None


@dataclass
class ChannelDecoder:
    by_id: dict[tuple[int, bool], tuple[Any, str]] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)


class DbcStore:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "dbc"
        self.assign_file = self.dir / "channels.json"
        self.files: dict[str, DbcFile] = {}
        self.assignments: dict[str, list[str]] = {}
        self._decoders: dict[str, ChannelDecoder] = {}
        self.live: dict[str, dict[tuple[int, bool], LiveEntry]] = {}

    # Laden / Speichern ------------------------------------------------------------------
    def load(self) -> None:
        self.files.clear()
        if self.dir.is_dir():
            for f in sorted(self.dir.glob("*.dbc")):
                try:
                    self.files[f.stem] = self._parse(
                        f.stem, f.name, f.read_text(encoding="utf-8", errors="replace"), f
                    )
                except ValidationFailed as exc:
                    log.error("DBC %s ungültig: %s", f.name, exc.message)
        if self.assign_file.exists():
            try:
                raw = json.loads(self.assign_file.read_text(encoding="utf-8"))
                self.assignments = {
                    str(k): [i for i in v if i in self.files] for k, v in raw.items() if isinstance(v, list)
                }
            except (OSError, ValueError) as exc:
                log.warning("DBC-Zuordnung nicht lesbar: %s", exc)
        self._rebuild()

    def _persist_assignments(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in self.assignments.items() if v}
        self.assign_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _parse(fid: str, name: str, text: str, path: Path) -> DbcFile:
        import cantools

        try:
            db = cantools.database.load_string(text, database_format="dbc", strict=False)
        except Exception as exc:
            raise ValidationFailed(f"DBC {name!r} konnte nicht gelesen werden: {exc}") from exc
        return DbcFile(fid, name, path, db, path.stat().st_mtime if path.exists() else time.time(), len(text))

    # Verwaltung ---------------------------------------------------------------------------
    def list_items(self) -> list[dict[str, Any]]:
        out = []
        for f in self.files.values():
            s = f.summary()
            s["channels"] = sorted(ch for ch, ids in self.assignments.items() if f.id in ids)
            out.append(s)
        return out

    def get(self, fid: str) -> DbcFile:
        if fid not in self.files:
            raise NotFoundError(f"DBC {fid!r} nicht gefunden")
        return self.files[fid]

    def add(self, filename: str, content: str, *, overwrite: bool = False) -> DbcFile:
        if len(content.encode("utf-8", errors="replace")) > MAX_DBC_BYTES:
            raise ValidationFailed("DBC-Datei ist zu groß (max. 20 MB)")
        fid = _slug(filename)
        if fid in self.files and not overwrite:
            raise ValidationFailed(f"DBC {fid!r} existiert bereits (overwrite=true zum Ersetzen)")
        path = self.dir / f"{fid}.dbc"
        parsed = self._parse(fid, filename, content, path)  # erst prüfen, dann speichern
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        parsed.added = time.time()
        self.files[fid] = parsed
        self._rebuild()
        return parsed

    def delete(self, fid: str) -> None:
        f = self.get(fid)
        f.path.unlink(missing_ok=True)
        del self.files[fid]
        for ch in list(self.assignments):
            self.assignments[ch] = [i for i in self.assignments[ch] if i != fid]
        self._persist_assignments()
        self._rebuild()

    def assign(self, channel: str, ids: list[str]) -> list[str]:
        for i in ids:
            self.get(i)
        self.assignments[channel] = list(dict.fromkeys(ids))
        self._persist_assignments()
        self._rebuild()
        self.live.pop(channel, None)
        return self.assignments[channel]

    def _rebuild(self) -> None:
        self._decoders.clear()
        for ch, ids in self.assignments.items():
            dec = ChannelDecoder()
            for fid in ids:
                f = self.files.get(fid)
                if f is None:
                    continue
                for m in f.db.messages:
                    key = (m.frame_id, bool(m.is_extended_frame))
                    if key in dec.by_id:
                        other = dec.by_id[key]
                        dec.conflicts.append(
                            f"CAN-ID 0x{m.frame_id:X}: {m.name!r} ({fid}) verdeckt durch {other[0].name!r} ({other[1]})"
                        )
                        continue
                    dec.by_id[key] = (m, fid)
            self._decoders[ch] = dec

    def conflicts(self) -> dict[str, list[str]]:
        return {ch: d.conflicts for ch, d in self._decoders.items() if d.conflicts}

    # Dekodieren ---------------------------------------------------------------------------
    def lookup(self, channel: str, frame_id: int, extended: bool) -> tuple[Any, str] | None:
        dec = self._decoders.get(channel)
        if not dec:
            return None
        return dec.by_id.get((frame_id, extended))

    def decode_frame(self, frame: CanFrame) -> dict[str, Any] | None:
        """Frame mit den DBCs seines Kanals dekodieren; aktualisiert die Live-Werte."""
        hit = self.lookup(frame.channel or "default", frame.arbitration_id, frame.is_extended_id)
        if hit is None or frame.is_error_frame or frame.is_remote_frame:
            return None
        msg, fid = hit
        try:
            raw = msg.decode(
                bytes(frame.data), decode_choices=True, scaling=True, allow_truncated=True, allow_excess=True
            )
        except Exception as exc:
            return {"message": msg.name, "dbc": fid, "error": str(exc), "signals": {}}
        signals = {k: _value(v) for k, v in raw.items()}
        units = {s.name: s.unit for s in msg.signals if s.unit and s.name in signals}
        ch = frame.channel or "default"
        key = (frame.arbitration_id, frame.is_extended_id)
        store = self.live.setdefault(ch, {})
        prev = store.get(key)
        ts = frame.timestamp or time.time()
        entry = LiveEntry(
            message=msg.name,
            dbc=fid,
            frame_id=frame.arbitration_id,
            extended=frame.is_extended_id,
            signals=signals,
            units=units,
            data=bytes(frame.data).hex(" ").upper(),
            ts=ts,
            count=(prev.count + 1) if prev else 1,
            dir=frame.direction,
            period_ms=round((ts - prev.ts) * 1000, 1) if prev else None,
        )
        store[key] = entry
        return {"message": msg.name, "dbc": fid, "signals": signals, "units": units}

    @staticmethod
    def describe(decoded: dict[str, Any], max_signals: int = 8) -> str:
        """Kurztext für die Trace-Spalte: ``Name: sig=1.5 V, mode=active``."""
        if decoded.get("error"):
            return f"{decoded['message']}: {decoded['error']}"
        units = decoded.get("units", {})
        parts = []
        for k, v in list(decoded["signals"].items())[:max_signals]:
            val = f"{v:g}" if isinstance(v, float) else str(v)
            parts.append(f"{k}={val}{' ' + units[k] if k in units else ''}")
        more = len(decoded["signals"]) - max_signals
        if more > 0:
            parts.append(f"… (+{more})")
        return f"{decoded['message']}: {', '.join(parts)}" if parts else str(decoded["message"])

    def live_items(self, channel: str) -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for e in self.live.get(channel, {}).values():
            out.append(
                {
                    "message": e.message,
                    "dbc": e.dbc,
                    "id": e.frame_id,
                    "id_hex": f"{e.frame_id:X}",
                    "extended": e.extended,
                    "signals": e.signals,
                    "units": e.units,
                    "data": e.data,
                    "ts": e.ts,
                    "age_s": round(now - e.ts, 2),
                    "count": e.count,
                    "dir": e.dir,
                    "period_ms": e.period_ms,
                }
            )
        return sorted(out, key=lambda x: (x["id"], x["extended"]))

    # Beschreibung / Kodieren ----------------------------------------------------------------
    def describe_file(self, fid: str) -> dict[str, Any]:
        f = self.get(fid)
        msgs = []
        for m in sorted(f.db.messages, key=lambda m: m.frame_id):
            msgs.append(
                {
                    "name": m.name,
                    "id": m.frame_id,
                    "id_hex": f"{m.frame_id:X}",
                    "extended": bool(m.is_extended_frame),
                    "fd": bool(getattr(m, "is_fd", False)),
                    "length": m.length,
                    "cycle_time": m.cycle_time,
                    "senders": list(m.senders or []),
                    "comment": m.comment,
                    "signals": [signal_info(s) for s in m.signals],
                }
            )
        return {**f.summary(), "nodes": [n.name for n in f.db.nodes], "messages": msgs}

    def find_message(self, channel: str, name: str, fid: str | None = None) -> tuple[Any, str]:
        ids = [fid] if fid else self.assignments.get(channel, [])
        for i in ids:
            f = self.get(i)
            try:
                return f.db.get_message_by_name(name), i
            except KeyError:
                continue
        raise NotFoundError(f"Botschaft {name!r} in den DBCs von Kanal {channel!r} nicht gefunden")

    @staticmethod
    def encode(msg: Any, values: dict[str, Any]) -> bytes:
        """Botschaft kodieren; nicht angegebene Signale bekommen ihren Startwert bzw. 0."""
        data: dict[str, Any] = {}
        for s in msg.signals:
            init = getattr(s, "initial", None)
            data[s.name] = init if init is not None else (s.minimum if s.minimum is not None else 0)
        for k, v in values.items():
            if k not in data:
                raise ValidationFailed(f"Signal {k!r} gehört nicht zu {msg.name!r}")
            data[k] = v
        # Multiplex: nur Signale des gewählten Zweigs (bzw. ohne Multiplexer-Bindung) kodieren
        by_name = {s.name: s for s in msg.signals}
        for name in list(data):
            s = by_name[name]
            sel = getattr(s, "multiplexer_signal", None)
            if s.multiplexer_ids and sel in data and data[sel] not in s.multiplexer_ids:
                if name in values:
                    raise ValidationFailed(
                        f"Signal {name!r} gilt nur bei {sel} ∈ {list(s.multiplexer_ids)}, nicht bei {data[sel]}"
                    )
                del data[name]
        try:
            return bytes(msg.encode(data, scaling=True, strict=True))
        except Exception as exc:
            raise ValidationFailed(f"Kodieren von {msg.name!r} fehlgeschlagen: {exc}") from exc


def signal_info(s: Any) -> dict[str, Any]:
    choices = {int(k): str(v) for k, v in (s.choices or {}).items()}
    return {
        "name": s.name,
        "start": s.start,
        "length": s.length,
        "byte_order": s.byte_order,
        "signed": bool(s.is_signed),
        "float": bool(s.is_float),
        "scale": s.scale,
        "offset": s.offset,
        "minimum": s.minimum,
        "maximum": s.maximum,
        "unit": s.unit or "",
        "choices": choices or None,
        "comment": s.comment,
        "multiplexer": bool(s.is_multiplexer),
        "multiplexer_ids": list(s.multiplexer_ids) if s.multiplexer_ids else None,
    }
