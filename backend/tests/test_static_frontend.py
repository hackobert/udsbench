"""Das gebaute Frontend ist eingecheckt, damit udsbench ohne Node.js/npm installierbar ist."""

from __future__ import annotations

import re

from udsbench.server import STATIC_DIR


def test_built_frontend_is_present() -> None:
    index = STATIC_DIR / "index.html"
    assert index.is_file(), (
        "backend/udsbench/static/index.html fehlt – 'cd frontend && npm run build' ausführen"
    )
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="/(assets/[^"]+)"', html)
    assert any(r.endswith(".js") for r in refs), "index.html verweist auf kein JavaScript-Bundle"
    for ref in refs:
        assert (STATIC_DIR / ref).is_file(), f"index.html verweist auf fehlende Datei {ref}"


def test_no_stale_assets() -> None:
    """Alte Bundles nach einem Neubau nicht liegen lassen (Vite leert das Ausgabeverzeichnis)."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for asset in (STATIC_DIR / "assets").iterdir():
        assert f"/assets/{asset.name}" in html, f"nicht referenzierte Datei {asset.name} in static/assets"
