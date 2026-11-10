from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from udsbench.can.channel import CanChannel
from udsbench.config.schema import AppConfig, ConnectionSpec
from udsbench.core.platform import Platform

REPO = Path(__file__).resolve().parents[2]
DEMO_PACKAGES = REPO / "config" / "packages"
_bus = itertools.count(1)


def unique_bus() -> str:
    return f"pytest_bus_{next(_bus)}"


def make_config(tmp_path: Path, **overrides: object) -> AppConfig:
    data: dict[str, object] = {
        "paths": {
            "package_dirs": [str(DEMO_PACKAGES)],
            "data_dir": str(tmp_path / "data"),
            "reports_dir": str(tmp_path / "reports"),
            "recordings_dir": str(tmp_path / "recordings"),
            "plugins_dir": str(tmp_path / "plugins"),
            "providers_dir": str(tmp_path / "providers"),
        },
        "logging": {"dir": str(tmp_path / "logs"), "level": "INFO", "console": False},
        "active_packages": ["demo"],
    }
    data.update(overrides)
    return AppConfig.model_validate(data)


@pytest.fixture
async def platform(tmp_path: Path):
    p = Platform(make_config(tmp_path), tmp_path)
    await p.start()
    await p.connect(
        ConnectionSpec(name="default", backend="virtual", options={"bus": unique_bus()}, simulate=True)
    )
    yield p
    await p.stop()


@pytest.fixture
async def bus_pair():
    """Zwei offene CAN-Kanäle auf demselben virtuellen Bus (Tester/ECU)."""
    name = unique_bus()
    a = CanChannel("a", "virtual", {"bus": name})
    b = CanChannel("b", "virtual", {"bus": name})
    await a.open()
    await b.open()
    yield a, b
    await a.close()
    await b.close()
