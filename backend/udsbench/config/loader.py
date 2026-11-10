"""Laden/Validieren/Speichern von App-Konfiguration und Konfig-Paketen."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..core.errors import ValidationFailed
from .schema import AppConfig, Package


def load_structured(text: str, fmt: str | None = None) -> Any:
    """Parst YAML oder JSON (JSON ist eine Teilmenge von YAML). Markdown-Codeblöcke (z. B. aus
    einer KI-Antwort) werden automatisch entfernt."""
    if "```" in text:
        from .ai_prompt import extract_yaml

        text = extract_yaml(text)
    try:
        if fmt == "json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ValidationFailed(f"Datei kann nicht gelesen werden: {exc}") from exc


def format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": ".".join(str(p) for p in err["loc"]), "msg": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]


def parse_package(data: Any) -> Package:
    if not isinstance(data, dict):
        raise ValidationFailed("Paket muss ein Objekt/Mapping sein")
    try:
        return Package.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed("Paket ist ungültig", details=format_validation_error(exc)) from exc


def load_package_file(path: Path) -> Package:
    text = path.read_text(encoding="utf-8")
    return parse_package(load_structured(text, "json" if path.suffix == ".json" else None))


def package_hash(pkg: Package) -> str:
    raw = json.dumps(pkg.model_dump(mode="json", by_alias=True), sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def dump_package(pkg: Package, fmt: str = "yaml") -> str:
    data = pkg.model_dump(mode="json", by_alias=True, exclude_defaults=False)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_app_config(path: Path | None) -> tuple[AppConfig, Path | None]:
    """Lädt die App-Konfiguration. Ohne Datei werden neutrale Defaults verwendet."""
    data: dict[str, Any] = {}
    if path is not None:
        if not path.exists():
            raise ValidationFailed(f"Konfigurationsdatei {path} nicht gefunden")
        data = load_structured(path.read_text(encoding="utf-8")) or {}
    try:
        cfg = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ValidationFailed(
            "App-Konfiguration ist ungültig", details=format_validation_error(exc)
        ) from exc
    env_token = os.environ.get("UDSBENCH_TOKEN")
    if env_token:
        cfg.server.token = env_token
    return cfg, path


def resolve(base: Path, p: str) -> Path:
    pp = Path(os.path.expandvars(os.path.expanduser(p)))
    return pp if pp.is_absolute() else (base / pp).resolve()


def safe_name(name: str) -> str:
    """Prüft Dateinamen-Bausteine (keine Pfadtrenner, kein ..)."""
    if not name or any(c in name for c in "/\\") or name in (".", "..") or ":" in name:
        raise ValidationFailed(f"Ungültiger Name {name!r}")
    return name
