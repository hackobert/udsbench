"""Plugin-Registry: eigene Decoder, Assertions und Seed-to-Key-Provider.

Plugins sind Python-Dateien in ``paths.plugins_dir``. Jede Datei kann eine Funktion
``register(registry)`` bereitstellen und darüber Erweiterungen anmelden::

    def register(registry):
        registry.add_decoder("my_struct", lambda data, spec: {...})
        registry.add_assertion("crc_ok", lambda ctx, result, params: (True, "ok"))
        registry.add_key_function("my_algo", lambda seed, level, params: bytes(...))

Das Tool selbst enthält keine herstellerspezifischen Plugins.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("udsbench.app.plugins")


class PluginRegistry:
    def __init__(self) -> None:
        self.decoders: dict[str, Callable[..., Any]] = {}
        self.assertions: dict[str, Callable[..., Any]] = {}
        self.key_functions: dict[str, Callable[[bytes, int, dict[str, Any]], bytes]] = {}
        self.loaded: list[dict[str, Any]] = []

    def add_decoder(self, name: str, fn: Callable[..., Any]) -> None:
        self.decoders[name] = fn

    def add_assertion(self, name: str, fn: Callable[..., Any]) -> None:
        self.assertions[name] = fn

    def add_key_function(self, name: str, fn: Callable[[bytes, int, dict[str, Any]], bytes]) -> None:
        self.key_functions[name] = fn

    def load_dir(self, path: Path) -> None:
        if not path.is_dir():
            return
        for file in sorted(path.glob("*.py")):
            if file.name.startswith("_") or ".example." in file.name:
                continue
            entry: dict[str, Any] = {"file": file.name, "ok": False}
            try:
                spec = importlib.util.spec_from_file_location(f"udsbench_plugin_{file.stem}", file)
                assert spec and spec.loader
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "register"):
                    mod.register(self)
                entry["ok"] = True
            except Exception as exc:
                entry["error"] = str(exc)
                log.error("Plugin %s konnte nicht geladen werden: %s", file.name, exc)
            self.loaded.append(entry)

    def summary(self) -> dict[str, Any]:
        return {
            "decoders": sorted(self.decoders),
            "assertions": sorted(self.assertions),
            "key_functions": sorted(self.key_functions),
            "files": self.loaded,
        }


registry = PluginRegistry()
