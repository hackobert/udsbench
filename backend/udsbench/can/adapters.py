"""CAN-Adapter-Abstraktion.

Einheitliche Schnittstelle ``open/close/send/status/reset``. Empfangene Frames werden über einen
Callback im asyncio-Eventloop geliefert. Konkrete Adapter:

* ``virtual``  – prozessinterner virtueller Bus (Loopback, mehrere Knoten, z. B. ECU-Testdouble)
* ``python-can`` – generischer Adapter über die python-can-Abstraktion (SocketCAN, serielle
  Adapter, herstellerspezifische Treiber, die python-can kapselt …). Welcher Treiber verwendet
  wird, kommt ausschließlich aus der Konfiguration (``interface``, ``channel``, ``bitrate`` …).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..core.errors import TransportError
from .frame import CanFrame

log = logging.getLogger("udsbench.app.can")

FrameCallback = Callable[[CanFrame], None]


class CanAdapter(ABC):
    kind = "abstract"

    def __init__(self, channel_name: str, options: dict[str, Any]) -> None:
        self.channel_name = channel_name
        self.options = dict(options)
        self._on_frame: FrameCallback | None = None
        self.is_open = False

    @abstractmethod
    async def open(self, on_frame: FrameCallback) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def send(self, frame: CanFrame) -> None: ...

    def status(self) -> dict[str, Any]:
        return {"kind": self.kind, "open": self.is_open, "options": _safe_options(self.options)}

    async def reset(self) -> None:
        await self.close()
        if self._on_frame:
            await self.open(self._on_frame)


def _safe_options(opts: dict[str, Any]) -> dict[str, Any]:
    masked = {}
    for k, v in opts.items():
        masked[k] = "***" if any(s in k.lower() for s in ("password", "secret", "token", "key")) else v
    return masked


# --------------------------------------------------------------------------------------------
# Virtueller Bus
# --------------------------------------------------------------------------------------------


class VirtualHub:
    """Ein virtueller CAN-Bus: alle angeschlossenen Knoten sehen die Frames der anderen."""

    _hubs: dict[str, VirtualHub] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self.nodes: list[VirtualAdapter] = []
        self.frames_total = 0

    @classmethod
    def get(cls, name: str) -> VirtualHub:
        if name not in cls._hubs:
            cls._hubs[name] = VirtualHub(name)
        return cls._hubs[name]

    @classmethod
    def reset_all(cls) -> None:
        cls._hubs.clear()

    def attach(self, node: VirtualAdapter) -> None:
        if node not in self.nodes:
            self.nodes.append(node)

    def detach(self, node: VirtualAdapter) -> None:
        if node in self.nodes:
            self.nodes.remove(node)

    def broadcast(self, frame: CanFrame, sender: VirtualAdapter) -> None:
        self.frames_total += 1
        for node in list(self.nodes):
            if node is sender and not node.receive_own:
                continue
            node._deliver(frame)


class VirtualAdapter(CanAdapter):
    kind = "virtual"

    def __init__(self, channel_name: str, options: dict[str, Any]) -> None:
        super().__init__(channel_name, options)
        self.bus_name = str(options.get("bus", options.get("channel", "vbus0")))
        self.receive_own = bool(options.get("receive_own_messages", False))
        self.fd = bool(options.get("fd", True))
        self._loop: asyncio.AbstractEventLoop | None = None
        self.hub: VirtualHub | None = None

    async def open(self, on_frame: FrameCallback) -> None:
        self._on_frame = on_frame
        self._loop = asyncio.get_running_loop()
        self.hub = VirtualHub.get(self.bus_name)
        self.hub.attach(self)
        self.is_open = True

    async def close(self) -> None:
        if self.hub:
            self.hub.detach(self)
        self.is_open = False

    async def send(self, frame: CanFrame) -> None:
        if not self.is_open or not self.hub:
            raise TransportError("Virtueller Adapter ist nicht geöffnet")
        if frame.is_fd and not self.fd:
            raise TransportError("CAN-FD ist auf diesem virtuellen Bus deaktiviert")
        copy = CanFrame(
            arbitration_id=frame.arbitration_id,
            data=bytes(frame.data),
            is_extended_id=frame.is_extended_id,
            is_fd=frame.is_fd,
            bitrate_switch=frame.bitrate_switch,
            is_remote_frame=frame.is_remote_frame,
            timestamp=time.time(),
            direction="rx",
        )
        self.hub.broadcast(copy, self)

    def _deliver(self, frame: CanFrame) -> None:
        if not self.is_open or not self._on_frame or not self._loop:
            return
        rx = CanFrame(
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            is_extended_id=frame.is_extended_id,
            is_fd=frame.is_fd,
            bitrate_switch=frame.bitrate_switch,
            is_remote_frame=frame.is_remote_frame,
            timestamp=frame.timestamp,
            direction="rx",
            channel=self.channel_name,
        )
        self._loop.call_soon(self._on_frame, rx)

    def status(self) -> dict[str, Any]:
        st = super().status()
        st.update(
            {
                "bus": self.bus_name,
                "nodes": len(self.hub.nodes) if self.hub else 0,
                "state": "ACTIVE" if self.is_open else "CLOSED",
                "fd": self.fd,
            }
        )
        return st


# --------------------------------------------------------------------------------------------
# python-can
# --------------------------------------------------------------------------------------------


class PythonCanAdapter(CanAdapter):
    """Generischer Adapter über python-can. Alle Parameter stammen aus der Konfiguration."""

    kind = "python-can"

    def __init__(self, channel_name: str, options: dict[str, Any]) -> None:
        super().__init__(channel_name, options)
        self._bus: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.errors = 0
        self.last_error: str | None = None

    def _bus_kwargs(self) -> dict[str, Any]:
        o = dict(self.options)
        kwargs: dict[str, Any] = {}
        if "interface" not in o:
            raise TransportError("python-can: 'interface' fehlt in der Verbindungskonfiguration")
        kwargs["interface"] = o.pop("interface")
        if "channel" in o:
            kwargs["channel"] = o.pop("channel")
        if o.get("bitrate"):
            kwargs["bitrate"] = int(o.pop("bitrate"))
        else:
            o.pop("bitrate", None)
        if o.pop("fd", False):
            kwargs["fd"] = True
            if o.get("data_bitrate"):
                kwargs["data_bitrate"] = int(o.pop("data_bitrate"))
        o.pop("data_bitrate", None)
        kwargs["receive_own_messages"] = bool(o.pop("receive_own_messages", False))
        kwargs.update(o.pop("extra", {}) or {})
        kwargs.update(o)  # weitere, treiberspezifische Parameter unverändert durchreichen
        if kwargs["interface"] == "pcan" and kwargs.get("fd"):
            _pcan_fd_timing(kwargs)
        return kwargs

    async def open(self, on_frame: FrameCallback) -> None:
        try:
            import can  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise TransportError("python-can ist nicht installiert") from exc
        self._on_frame = on_frame
        self._loop = asyncio.get_running_loop()
        kwargs = self._bus_kwargs()
        timeout = float(self.options.get("open_timeout_s", 10))

        def _create() -> Any:
            import can

            return can.Bus(**kwargs)

        try:
            self._bus = await asyncio.wait_for(self._loop.run_in_executor(None, _create), timeout)
        except TimeoutError as exc:
            raise TransportError(f"Öffnen des CAN-Interfaces dauerte länger als {timeout}s") from exc
        except Exception as exc:
            raise TransportError(
                _open_error_message(str(kwargs["interface"]), kwargs.get("channel"), exc)
            ) from exc
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, name=f"can-rx-{self.channel_name}", daemon=True)
        self._thread.start()
        self.is_open = True

    def _reader(self) -> None:
        assert self._bus is not None
        while not self._stop.is_set():
            try:
                msg = self._bus.recv(0.1)
            except Exception as exc:  # pragma: no cover - hardwareabhängig
                self.errors += 1
                self.last_error = str(exc)
                time.sleep(0.05)
                continue
            if msg is None:
                continue
            frame = CanFrame(
                arbitration_id=msg.arbitration_id,
                data=bytes(msg.data),
                is_extended_id=bool(msg.is_extended_id),
                is_fd=bool(getattr(msg, "is_fd", False)),
                bitrate_switch=bool(getattr(msg, "bitrate_switch", False)),
                is_error_frame=bool(msg.is_error_frame),
                is_remote_frame=bool(msg.is_remote_frame),
                timestamp=float(msg.timestamp or time.time()),
                direction="tx" if getattr(msg, "is_rx", True) is False else "rx",
                channel=self.channel_name,
            )
            if frame.direction == "tx":
                continue  # eigene Frames werden bereits beim Senden protokolliert
            if self._loop and self._on_frame:
                with contextlib.suppress(RuntimeError):
                    self._loop.call_soon_threadsafe(self._on_frame, frame)

    async def close(self) -> None:
        self._stop.set()
        if self._thread:
            await asyncio.get_running_loop().run_in_executor(None, self._thread.join, 2.0)
            self._thread = None
        if self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.shutdown()
            self._bus = None
        self.is_open = False

    async def send(self, frame: CanFrame) -> None:
        if not self._bus:
            raise TransportError("CAN-Interface ist nicht geöffnet")
        import can

        msg = can.Message(
            arbitration_id=frame.arbitration_id,
            data=frame.data,
            is_extended_id=frame.is_extended_id,
            is_fd=frame.is_fd,
            bitrate_switch=frame.bitrate_switch,
            is_remote_frame=frame.is_remote_frame,
        )
        timeout = float(self.options.get("send_timeout_s", 1.0))
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._bus.send, msg, timeout)
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            raise TransportError(f"Senden fehlgeschlagen: {exc}") from exc

    def status(self) -> dict[str, Any]:
        st = super().status()
        state = None
        info = None
        if self._bus is not None:
            with contextlib.suppress(Exception):
                state = str(self._bus.state.name)
            info = getattr(self._bus, "channel_info", None)
        st.update(
            {"state": state, "channel_info": info, "errors": self.errors, "last_error": self.last_error}
        )
        return st


# Interne Taktfrequenz der PCAN-FD-Hardware; python-can erwartet bei FD Bit-Timing statt Bitraten
PCAN_FD_CLOCK = 80_000_000
_PCAN_FD_TIMING_KEYS = ("timing", "f_clock", "f_clock_mhz", "nom_brp")


def _pcan_fd_timing(kwargs: dict[str, Any]) -> None:
    """PCAN mit CAN-FD: aus ``bitrate``/``data_bitrate`` ein Bit-Timing berechnen.

    python-can ignoriert bei ``interface=pcan`` und ``fd=True`` die Bitraten und verlangt
    ``f_clock`` und Segmentwerte. Sind diese nicht explizit angegeben, wird ein Timing für
    80 MHz mit den Abtastpunkten ``sample_point``/``data_sample_point`` (Standard 80 %) berechnet.
    """
    nom_sp = float(kwargs.pop("sample_point", 80.0))
    data_sp = float(kwargs.pop("data_sample_point", 80.0))
    if any(k in kwargs for k in _PCAN_FD_TIMING_KEYS):
        return
    import can

    nom = int(kwargs.get("bitrate") or 500_000)
    data = int(kwargs.pop("data_bitrate", 0) or 2_000_000)
    try:
        kwargs["timing"] = can.BitTimingFd.from_sample_point(
            f_clock=PCAN_FD_CLOCK,
            nom_bitrate=nom,
            nom_sample_point=nom_sp,
            data_bitrate=data,
            data_sample_point=data_sp,
        )
    except ValueError as exc:
        raise TransportError(
            f"PCAN CAN-FD: kein Bit-Timing für {nom} / {data} Bit/s bei 80 MHz möglich ({exc}). "
            "Bitraten prüfen oder f_clock, nom_brp, nom_tseg1 … als Optionen angeben."
        ) from exc


def _open_error_message(interface: str, channel: Any, exc: Exception) -> str:
    """Fehlermeldung beim Öffnen um konkrete Hinweise ergänzen (häufige Treiberprobleme)."""
    detail = str(exc) or type(exc).__name__
    msg = f"CAN-Interface konnte nicht geöffnet werden ({interface}, Kanal {channel!r}): {detail}"
    low = detail.lower()
    hint = ""
    if interface == "pcan":
        if isinstance(exc, KeyError):
            msg = f"Unbekannter PCAN-Kanal {channel!r}."
            hint = "PCAN-Kanäle heißen z. B. PCAN_USBBUS1, PCAN_USBBUS2 oder PCAN_PCIBUS1."
        elif isinstance(exc, OSError) and ("library" in low or "pcanbasic" in low or ".dll" in low):
            hint = (
                "Die PCAN-Basic-Bibliothek fehlt. Windows: Gerätetreiber von PEAK-System installieren "
                "(enthält PCANBasic.dll). Linux: PCAN-Basic für Linux installieren oder den "
                "Kerneltreiber peak_usb mit interface 'socketcan' und Kanal 'can0' nutzen. "
                "macOS: PCBUSB-Bibliothek installieren."
            )
        elif "initialize" in low or "hardware" in low or "not found" in low or "illegal" in low:
            hint = (
                "Ist der Adapter angeschlossen und nicht von einem anderen Programm (z. B. PCAN-View) "
                "belegt? Kanal und Bitrate prüfen."
            )
    elif interface == "socketcan" and ("no such device" in low or "network is down" in low):
        hint = f"Schnittstelle vorher aktivieren: sudo ip link set {channel or 'can0'} up type can bitrate 500000"
    elif isinstance(exc, KeyError):
        msg = f"Unbekannter Kanal {channel!r} für Interface {interface!r}."
    return f"{msg} {hint}".strip()


ADAPTERS: dict[str, type[CanAdapter]] = {
    "virtual": VirtualAdapter,
    "python-can": PythonCanAdapter,
}


def create_adapter(backend: str, channel_name: str, options: dict[str, Any]) -> CanAdapter:
    try:
        cls = ADAPTERS[backend]
    except KeyError as exc:
        raise TransportError(f"Unbekanntes CAN-Backend {backend!r}. Verfügbar: {sorted(ADAPTERS)}") from exc
    return cls(channel_name, options)


def list_interfaces(detect: bool = False, interface: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"backends": sorted(ADAPTERS), "python_can_interfaces": [], "detected": []}
    try:
        import can

        result["python_can_interfaces"] = sorted(getattr(can.interfaces, "VALID_INTERFACES", []))
        if detect:
            try:
                result["detected"] = [
                    {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in cfg.items()}
                    for cfg in can.detect_available_configs(interface or None)
                ]
            except Exception as exc:  # pragma: no cover
                result["detect_error"] = str(exc)
    except ImportError:  # pragma: no cover
        pass
    return result
