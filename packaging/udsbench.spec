# PyInstaller-Spezifikation für einen Ein-Datei-Build je Plattform.
#   cd frontend && npm ci && npm run build && cd ..
#   pip install .[build] && pyinstaller packaging/udsbench.spec
# Ergebnis: dist/udsbench(.exe) – Start ohne Argumente öffnet die UI im Browser.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH).parent  # noqa: F821
pkg = root / "backend" / "udsbench"
datas = [(str(root / "config" / "packages"), "udsbench/_bundled/packages"),
         (str(root / "config" / "app.example.yaml"), "udsbench/_bundled")]
# Lizenztexte mitliefern (u. a. LGPL-3.0 von python-can, siehe THIRD_PARTY_NOTICES.md)
datas += copy_metadata("python-can")
for f in ("LICENSE", "THIRD_PARTY_NOTICES.md", "AI_DISCLOSURE.md"):
    datas.append((str(root / f), "licenses"))
if (pkg / "static").is_dir():
    datas.append((str(pkg / "static"), "udsbench/static"))

a = Analysis(  # noqa: F821
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "backend")],
    datas=datas,
    hiddenimports=collect_submodules("udsbench") + collect_submodules("can.interfaces") + collect_submodules("uvicorn"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="udsbench", console=True, upx=False)  # noqa: F821
