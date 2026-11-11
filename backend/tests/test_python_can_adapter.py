"""python-can-Adapter: Parameteraufbereitung und Fehlermeldungen (ohne Hardware)."""

from __future__ import annotations

import can
import pytest

from udsbench.can.adapters import PCAN_FD_CLOCK, PythonCanAdapter, _open_error_message
from udsbench.core.errors import TransportError


def kwargs_for(**options: object) -> dict[str, object]:
    return PythonCanAdapter("default", options)._bus_kwargs()


def test_classic_can_passes_bitrate() -> None:
    kw = kwargs_for(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000)
    assert kw["bitrate"] == 500000 and "timing" not in kw


def test_pcan_fd_computes_bit_timing() -> None:
    kw = kwargs_for(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000, fd=True, data_bitrate=2000000)
    timing = kw["timing"]
    assert isinstance(timing, can.BitTimingFd)
    assert timing.f_clock == PCAN_FD_CLOCK
    assert timing.nom_bitrate == 500000 and timing.data_bitrate == 2000000
    assert "data_bitrate" not in kw


def test_pcan_fd_explicit_timing_wins() -> None:
    kw = kwargs_for(interface="pcan", fd=True, data_bitrate=2000000, f_clock_mhz=80, nom_brp=2)
    assert "timing" not in kw and kw["f_clock_mhz"] == 80


def test_pcan_fd_impossible_timing() -> None:
    with pytest.raises(TransportError, match="Bit-Timing"):
        kwargs_for(interface="pcan", fd=True, bitrate=123457, data_bitrate=7777777)


def test_other_interfaces_unchanged() -> None:
    kw = kwargs_for(interface="socketcan", channel="can0", fd=True, data_bitrate=2000000, sample_point=0.8)
    assert kw["data_bitrate"] == 2000000 and kw["sample_point"] == 0.8 and "timing" not in kw


def test_error_hints() -> None:
    msg = _open_error_message("pcan", "can0", KeyError("can0"))
    assert "Unbekannter PCAN-Kanal 'can0'" in msg and "PCAN_USBBUS1" in msg
    msg = _open_error_message("pcan", "PCAN_USBBUS1", OSError("pcanbasic library not found."))
    assert "PCAN-Basic" in msg and "PEAK" in msg
    msg = _open_error_message("socketcan", "can0", OSError("[Errno 19] No such device"))
    assert "ip link set can0 up" in msg
