"""Kommandozeile: ``udsbench run | validate | schema | init``."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__


def _find_config(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get("UDSBENCH_CONFIG")
    if env:
        return Path(env)
    for cand in (Path("config/app.yaml"), Path("app.yaml")):
        if cand.exists():
            return cand
    return None


def cmd_run(args: argparse.Namespace) -> int:
    import uvicorn

    from .config.loader import load_app_config
    from .config.schema import ConnectionSpec
    from .server import create_app

    cfg_path = _find_config(args.config)
    cfg, _ = load_app_config(cfg_path)
    base = Path.cwd()
    if args.host:
        cfg.server.host = args.host
    if args.port:
        cfg.server.port = args.port
    if args.token:
        cfg.server.token = args.token
    if args.log_level:
        cfg.logging.level = args.log_level
    from .config.loader import resolve
    from .core.setup_state import saved_connections

    # --demo nur, wenn weder app.yaml noch der Einrichtungsassistent eine Verbindung festlegen
    if args.demo and not cfg.connections and saved_connections(resolve(base, cfg.paths.data_dir)):
        print(
            "Hinweis: Gespeicherte Verbindung aus dem Einrichtungsassistenten wird verwendet (--demo ignoriert)."
        )
    elif args.demo and not cfg.connections:
        cfg.connections = [
            ConnectionSpec(name="default", backend="virtual", options={"bus": "vbus0"}, simulate=True)
        ]
    app = create_app(cfg, base)
    url = f"http://{'127.0.0.1' if cfg.server.host in ('0.0.0.0', '::') else cfg.server.host}:{cfg.server.port}/"
    token = app.state.token
    open_url = url + (f"#token={token}" if token else "")
    print(
        f"udsbench {__version__} – UI: {url}  API-Doku: {url}docs"
        + (f"\nAPI-Token: {token}" if token else ""),
        flush=True,
    )
    if args.open or (cfg.server.open_browser and not args.no_browser):
        threading.Timer(1.2, lambda: webbrowser.open(open_url)).start()
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="warning", ws="auto")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .config.loader import load_package_file
    from .core.errors import ValidationFailed

    rc = 0
    for f in args.files:
        try:
            pkg = load_package_file(Path(f))
            print(f"OK   {f}: Paket {pkg.package.id} v{pkg.package.version}")
        except ValidationFailed as exc:
            rc = 1
            print(f"FEHLER {f}: {exc.message}")
            for d in exc.details or []:
                print(f"   - {d['loc']}: {d['msg']}" if isinstance(d, dict) else f"   - {d}")
    return rc


def cmd_schema(args: argparse.Namespace) -> int:
    from .config.schema import AppConfig, Package

    model = Package if args.kind == "package" else AppConfig
    print(json.dumps(model.model_json_schema(by_alias=True), indent=2, ensure_ascii=False))
    return 0


def cmd_ai_prompt(args: argparse.Namespace) -> int:
    """Gibt den KI-Prompt zur Paketerstellung aus einer Spezifikation aus."""
    from .config.ai_prompt import SECTIONS_ALL, build_prompt

    secs = [s for s in (args.sections or "").split(",") if s] or list(SECTIONS_ALL)
    text = build_prompt(
        package_id=args.package_id or "",
        package_name=args.package_name or "",
        sections=secs,
        with_simulation=args.simulation,
        with_tests=not args.no_tests,
        notes=args.notes or "",
        include_json_schema=args.json_schema,
    )
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Prompt geschrieben: {args.output} ({len(text)} Zeichen)")
    else:
        print(text)
    return 0


def cmd_ai_check(args: argparse.Namespace) -> int:
    """Prüft eine KI-Antwort (Datei) und gibt bei Fehlern einen Korrektur-Prompt aus."""
    from .config.ai_prompt import build_fix_prompt, extract_yaml
    from .config.loader import load_structured, parse_package
    from .core.errors import ValidationFailed

    text = extract_yaml(Path(args.file).read_text(encoding="utf-8"))
    try:
        pkg = parse_package(load_structured(text))
    except ValidationFailed as exc:
        details = exc.details if isinstance(exc.details, list) else []
        print(build_fix_prompt(text, details, exc.message))
        return 1
    out = Path(args.output) if args.output else Path(f"{pkg.package.id}.yaml")
    out.write_text(text, encoding="utf-8")
    print(f"OK: Paket {pkg.package.id} v{pkg.package.version} gültig, gespeichert als {out}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Legt eine lokale Konfiguration im aktuellen Verzeichnis an."""
    target = Path("config")
    (target / "packages").mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent
    bundled = here / "_bundled"
    src_app = bundled / "app.example.yaml"
    if not src_app.exists():
        src_app = here.parent.parent / "config" / "app.example.yaml"
    if not (target / "app.yaml").exists() and src_app.exists():
        shutil.copy(src_app, target / "app.yaml")
        print("config/app.yaml angelegt")
    pk = bundled / "packages"
    if pk.is_dir():
        for f in pk.glob("*.example.yaml"):
            if not (target / "packages" / f.name).exists():
                shutil.copy(f, target / "packages" / f.name)
                print(f"config/packages/{f.name} angelegt")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="udsbench", description="Generische UDS-/CAN-Diagnose- und Testplattform"
    )
    ap.add_argument("--version", action="version", version=f"udsbench {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="Server starten (UI + API)")
    r.add_argument("-c", "--config", help="Pfad zur app.yaml (Default: config/app.yaml, $UDSBENCH_CONFIG)")
    r.add_argument("--host")
    r.add_argument("--port", type=int)
    r.add_argument("--token", help="API-Token (besser: $UDSBENCH_TOKEN)")
    r.add_argument("--log-level", choices=["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"])
    r.add_argument("--open", action="store_true", help="Browser öffnen")
    r.add_argument("--no-browser", action="store_true")
    r.add_argument("--demo", action="store_true", help="Virtuellen Bus mit ECU-Testdouble verbinden")
    r.set_defaults(fn=cmd_run)
    v = sub.add_parser("validate", help="Konfig-Pakete validieren")
    v.add_argument("files", nargs="+")
    v.set_defaults(fn=cmd_validate)
    s = sub.add_parser("schema", help="JSON-Schema ausgeben")
    s.add_argument("kind", choices=["package", "app"], nargs="?", default="package")
    s.set_defaults(fn=cmd_schema)
    a = sub.add_parser("ai-prompt", help="KI-Prompt: Konfig-Paket aus einer Spezifikation erstellen")
    a.add_argument("--package-id")
    a.add_argument("--package-name")
    a.add_argument(
        "--sections", help="Kommagetrennt, z. B. isotp,ecus,security,dids,dtcs,routines,messages,tests"
    )
    a.add_argument("--simulation", action="store_true", help="auch ein ECU-Testdouble beschreiben lassen")
    a.add_argument("--no-tests", action="store_true")
    a.add_argument("--notes", help="zusätzliche Hinweise an die KI")
    a.add_argument("--json-schema", action="store_true", help="vollständiges JSON-Schema anhängen")
    a.add_argument("-o", "--output")
    a.set_defaults(fn=cmd_ai_prompt)
    c = sub.add_parser("ai-check", help="KI-Antwort prüfen; bei Fehlern Korrektur-Prompt ausgeben")
    c.add_argument("file")
    c.add_argument("-o", "--output", help="gültiges Paket hierhin speichern")
    c.set_defaults(fn=cmd_ai_check)
    i = sub.add_parser("init", help="Lokale Konfiguration anlegen")
    i.set_defaults(fn=cmd_init)
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
