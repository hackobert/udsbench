"""Einstiegspunkt für den Ein-Datei-Build (PyInstaller)."""

import sys

from udsbench.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv += ["run", "--open"]
    sys.exit(main())
