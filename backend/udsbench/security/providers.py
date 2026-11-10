"""Austauschbare Seed-to-Key-Provider.

Stabile Schnittstelle::

    compute_key(seed: bytes, security_level: int, params: dict) -> bytes

Das Tool enthält **keine** proprietären Verfahren und **keine** Schlüssel. Provider-Typen:

* ``demo``   – frei erfundener, offen dokumentierter Spielzeug-Algorithmus (nur Test/Demo!)
* ``script`` – externes Programm/Script (stdin/stdout oder Dateien)
* ``native`` – vom Anwender bereitgestellte Shared Library (.dll/.so/.dylib), Signatur aus der Konfig
* ``python`` – Python-Datei mit ``compute_key(seed, level, params)``
* ``plugin`` – über die Plugin-Registry registrierte Funktion
"""

from __future__ import annotations

import asyncio
import ctypes
import importlib.util
import os
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.errors import ProviderError
from ..core.hexutil import parse_hex, to_hex


class SeedKeyProvider(ABC):
    type_name = "abstract"

    def __init__(self, provider_id: str, params: dict[str, Any], base_dir: Path) -> None:
        self.id = provider_id
        self.params = dict(params)
        self.base_dir = base_dir

    def merged(self, params: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(self.params)
        out.update(params or {})
        # ${ENV:NAME} → Umgebungsvariable (Zugangsdaten nie im Repo!)
        for k, v in list(out.items()):
            if isinstance(v, str) and v.startswith("${ENV:") and v.endswith("}"):
                out[k] = os.environ.get(v[6:-1], "")
        return out

    def path(self, p: str) -> Path:
        pp = Path(os.path.expandvars(os.path.expanduser(p)))
        return pp if pp.is_absolute() else (self.base_dir / pp)

    @abstractmethod
    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes: ...

    async def compute_key_async(
        self, seed: bytes, security_level: int, params: dict[str, Any] | None = None
    ) -> bytes:
        p = self.merged(params)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.compute_key, seed, security_level, p)

    def describe(self) -> dict[str, Any]:
        from ..logs.setup import get_masker

        m = get_masker()
        return {
            "id": self.id,
            "type": self.type_name,
            "params": {k: m.mask_value(k, v) for k, v in self.params.items()},
        }


# --------------------------------------------------------------------------------------------
class DemoProvider(SeedKeyProvider):
    """Spielzeug-Algorithmus – ausschließlich für Demo/Tests, **kein** reales Verfahren.

    Für jedes Seed-Byte ``s[i]``::

        x = s[i] XOR mask[i mod len(mask)] XOR (level * 0x11 mod 256)
        k[i] = ((x << 1) | (x >> 7)) & 0xFF            # um 1 Bit nach links rotieren
        k[i] = (k[i] + i) & 0xFF

    ``mask`` (Hex, Default ``"5A A5"``) und ``key_length`` (Default = Seed-Länge) sind Parameter.
    """

    type_name = "demo"

    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes:
        mask = parse_hex(params.get("mask", "5A A5")) or b"\x00"
        lv = (security_level * 0x11) & 0xFF
        out = bytearray()
        for i, s in enumerate(seed):
            x = s ^ mask[i % len(mask)] ^ lv
            k = ((x << 1) | (x >> 7)) & 0xFF
            out.append((k + i) & 0xFF)
        n = int(params.get("key_length", len(out)))
        return bytes((out * ((n // max(1, len(out))) + 1))[:n]) if out else bytes(n)


# --------------------------------------------------------------------------------------------
class ScriptProvider(SeedKeyProvider):
    """Externes Programm.

    Parameter:
      * ``command``: Liste oder String; Platzhalter ``{seed}``, ``{level}``, ``{seed_file}``,
        ``{key_file}`` und ``{param_NAME}``.
      * ``mode``: ``stdio`` (Seed als Hex auf stdin, Key als Hex auf stdout) oder ``file``.
      * ``timeout_s`` (Default 10), ``cwd``, ``env`` (Mapping; Werte ``${ENV:NAME}`` erlaubt).
    """

    type_name = "script"

    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes:
        cmd = params.get("command")
        if not cmd:
            raise ProviderError("script-Provider: 'command' fehlt")
        mode = params.get("mode", "stdio")
        timeout = float(params.get("timeout_s", 10))
        with tempfile.TemporaryDirectory() as td:
            seed_file = Path(td) / "seed.bin"
            key_file = Path(td) / "key.bin"
            seed_file.write_bytes(seed)
            fmt = {
                "seed": seed.hex().upper(),
                "level": str(security_level),
                "seed_file": str(seed_file),
                "key_file": str(key_file),
                "python": sys.executable,
            }
            fmt.update({f"param_{k}": str(v) for k, v in params.items() if isinstance(v, (str, int, float))})
            args = [str(a).format(**fmt) for a in cmd] if isinstance(cmd, list) else str(cmd).format(**fmt)
            env = dict(os.environ)
            for k, v in (params.get("env") or {}).items():
                env[k] = (
                    os.environ.get(v[6:-1], "") if isinstance(v, str) and v.startswith("${ENV:") else str(v)
                )
            try:
                proc = subprocess.run(
                    args,
                    input=(seed.hex().upper() + "\n") if mode == "stdio" else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=params.get("cwd") or None,
                    env=env,
                    shell=isinstance(args, str),
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderError(f"script-Provider: Timeout nach {timeout}s") from exc
            except OSError as exc:
                raise ProviderError(f"script-Provider: Start fehlgeschlagen: {exc}") from exc
            if proc.returncode != 0:
                raise ProviderError(
                    f"script-Provider: Exit-Code {proc.returncode}: {proc.stderr.strip()[:300]}"
                )
            if mode == "file":
                if not key_file.exists():
                    raise ProviderError("script-Provider: Key-Datei wurde nicht erzeugt")
                return key_file.read_bytes()
            out = proc.stdout.strip().splitlines()
            if not out:
                raise ProviderError("script-Provider: keine Ausgabe")
            return parse_hex(out[-1])


# --------------------------------------------------------------------------------------------
_CTYPES = {
    "int": ctypes.c_int,
    "uint": ctypes.c_uint,
    "int32": ctypes.c_int32,
    "uint32": ctypes.c_uint32,
    "int16": ctypes.c_int16,
    "uint16": ctypes.c_uint16,
    "uint8": ctypes.c_uint8,
    "int64": ctypes.c_int64,
    "uint64": ctypes.c_uint64,
    "size_t": ctypes.c_size_t,
    "void": None,
}


class NativeLibraryProvider(SeedKeyProvider):
    """Ruft eine Funktion einer vom Anwender bereitgestellten Shared Library auf.

    Die komplette Aufrufbeschreibung kommt aus der Konfiguration, z. B.::

        type: native
        params:
          library: providers/libkeygen.so          # relativ zu paths.providers_dir
          calling_convention: cdecl                # oder stdcall (nur Windows)
          function: GenerateKey
          return: {type: int, success: 0}
          key_buffer_size: 64
          args:                                    # Reihenfolge = C-Signatur
            - seed_ptr                             # const uint8_t*
            - {seed_len: uint32}
            - {level: uint32}
            - {const_str: "${ENV:KEYGEN_VARIANT}"} # Zugangsdaten nur per Umgebung
            - key_ptr                              # uint8_t* (Puffer der Größe key_buffer_size)
            - {key_buffer_size: uint32}
            - key_len_ptr                          # uint32_t* (out)
          init:                                    # optionale Initialisierungsaufrufe
            - {function: Init, args: [{const_str: "config.dat", path: true}], success: 0}

    Argument-Bausteine: ``seed_ptr``, ``seed_len``, ``level``, ``key_ptr``, ``key_buffer_size``,
    ``key_len_ptr``, ``key_len_in`` (fixe Key-Länge), ``const_int``, ``const_str`` (``path: true``
    löst relativ zum Provider-Verzeichnis auf), ``param`` (Name eines Parameters).
    Ist ``key_len_ptr`` nicht vorhanden, wird ``key_length`` (Parameter) bzw. die Seed-Länge verwendet.
    """

    type_name = "native"
    _libs: dict[str, Any] = {}

    def _load(self, params: dict[str, Any]) -> Any:
        lib_path = params.get("library")
        if not lib_path:
            raise ProviderError("native-Provider: 'library' fehlt")
        path = self.path(str(lib_path))
        if not path.exists():
            raise ProviderError(f"native-Provider: Bibliothek nicht gefunden: {path}")
        key = str(path)
        if key not in self._libs:
            cc = params.get("calling_convention", "cdecl")
            try:
                if cc == "stdcall" and sys.platform == "win32":
                    lib = ctypes.WinDLL(key)  # type: ignore[attr-defined]
                else:
                    lib = ctypes.CDLL(key)
            except OSError as exc:
                raise ProviderError(f"native-Provider: Laden fehlgeschlagen: {exc}") from exc
            for step in params.get("init", []) or []:
                self._call(
                    lib,
                    step["function"],
                    step.get("args", []),
                    b"",
                    0,
                    params,
                    step.get("return", {"type": "int", "success": step.get("success")}),
                )
            self._libs[key] = lib
        return self._libs[key]

    def _call(
        self,
        lib: Any,
        fname: str,
        arg_spec: list[Any],
        seed: bytes,
        level: int,
        params: dict[str, Any],
        ret: dict[str, Any],
    ) -> tuple[int | None, bytes | None, int | None]:
        try:
            fn = getattr(lib, fname)
        except AttributeError as exc:
            raise ProviderError(f"native-Provider: Funktion {fname!r} nicht gefunden") from exc
        buf_size = int(params.get("key_buffer_size", 256))
        seed_buf = (ctypes.c_uint8 * max(1, len(seed))).from_buffer_copy(seed or b"\x00")
        key_buf = (ctypes.c_uint8 * buf_size)()
        key_len = ctypes.c_uint32(0)
        args: list[Any] = []
        argtypes: list[Any] = []
        for a in arg_spec:
            name, typ = (a, "uint32") if isinstance(a, str) else next(iter(a.items()))
            if name == "seed_ptr":
                args.append(seed_buf)
                argtypes.append(ctypes.POINTER(ctypes.c_uint8))
            elif name == "key_ptr":
                args.append(key_buf)
                argtypes.append(ctypes.POINTER(ctypes.c_uint8))
            elif name == "key_len_ptr":
                args.append(ctypes.byref(key_len))
                argtypes.append(ctypes.POINTER(ctypes.c_uint32))
            elif name in ("seed_len", "level", "key_buffer_size", "key_len_in"):
                val = {
                    "seed_len": len(seed),
                    "level": level,
                    "key_buffer_size": buf_size,
                    "key_len_in": int(params.get("key_length", len(seed))),
                }[name]
                ct = _CTYPES.get(str(typ), ctypes.c_uint32)
                args.append(val)
                argtypes.append(ct)
            elif name == "const_int":
                args.append(int(typ) if not isinstance(typ, dict) else int(typ["value"]))
                argtypes.append(ctypes.c_int)
            elif name == "const_str":
                sval = typ if not isinstance(typ, dict) else typ["value"]
                if isinstance(sval, str) and sval.startswith("${ENV:"):
                    sval = os.environ.get(sval[6:-1], "")
                if isinstance(a, dict) and a.get("path"):
                    sval = str(self.path(str(sval)))
                args.append(ctypes.c_char_p(str(sval).encode()))
                argtypes.append(ctypes.c_char_p)
            elif name == "param":
                v = params.get(str(typ))
                if isinstance(v, int):
                    args.append(v)
                    argtypes.append(ctypes.c_int)
                else:
                    args.append(ctypes.c_char_p(str(v or "").encode()))
                    argtypes.append(ctypes.c_char_p)
            else:
                raise ProviderError(f"native-Provider: unbekannter Argument-Baustein {name!r}")
        fn.argtypes = argtypes
        rtype = ret.get("type", "int")
        fn.restype = _CTYPES.get(rtype, ctypes.c_int)
        rv = fn(*args)
        if ret.get("success") is not None and rv != ret["success"]:
            raise ProviderError(f"native-Provider: {fname} lieferte {rv} (erwartet {ret['success']})")
        has_len = any((a == "key_len_ptr") for a in arg_spec)
        n = key_len.value if has_len else int(params.get("key_length", len(seed)))
        return rv, bytes(key_buf[: min(n, buf_size)]), n

    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes:
        lib = self._load(params)
        fname = params.get("function")
        if not fname:
            raise ProviderError("native-Provider: 'function' fehlt")
        _, key, _ = self._call(
            lib,
            fname,
            params.get("args", []),
            seed,
            security_level,
            params,
            params.get("return", {"type": "int", "success": 0}),
        )
        return key or b""


# --------------------------------------------------------------------------------------------
class PythonFileProvider(SeedKeyProvider):
    """Python-Datei (z. B. in ``config/providers``) mit ``compute_key(seed, level, params) -> bytes``."""

    type_name = "python"

    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes:
        file = params.get("file")
        if not file:
            raise ProviderError("python-Provider: 'file' fehlt")
        path = self.path(str(file))
        if not path.exists():
            raise ProviderError(f"python-Provider: Datei nicht gefunden: {path}")
        spec = importlib.util.spec_from_file_location(f"udsbench_provider_{self.id}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, params.get("function", "compute_key"), None)
        if fn is None:
            raise ProviderError("python-Provider: Funktion nicht gefunden")
        res = fn(seed, security_level, params)
        return parse_hex(res) if isinstance(res, str) else bytes(res)


class PluginProvider(SeedKeyProvider):
    type_name = "plugin"

    def compute_key(self, seed: bytes, security_level: int, params: dict[str, Any]) -> bytes:
        from ..plugins.registry import registry

        name = params.get("function")
        fn = registry.key_functions.get(str(name))
        if fn is None:
            raise ProviderError(f"plugin-Provider: Funktion {name!r} nicht registriert")
        return bytes(fn(seed, security_level, params))


PROVIDER_TYPES: dict[str, type[SeedKeyProvider]] = {
    "demo": DemoProvider,
    "script": ScriptProvider,
    "native": NativeLibraryProvider,
    "python": PythonFileProvider,
    "plugin": PluginProvider,
}


def create_provider(
    provider_id: str, type_name: str, params: dict[str, Any], base_dir: Path
) -> SeedKeyProvider:
    cls = PROVIDER_TYPES.get(type_name)
    if cls is None:
        raise ProviderError(f"Unbekannter Provider-Typ {type_name!r}")
    return cls(provider_id, params, base_dir)


__all__ = ["PROVIDER_TYPES", "SeedKeyProvider", "create_provider", "to_hex"]
