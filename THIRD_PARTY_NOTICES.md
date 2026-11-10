# Third-Party Notices / Drittanbieter-Hinweise

udsbench itself is licensed under the MIT License (see `LICENSE`). It does **not** vendor or copy
third-party source code. The following packages are installed as runtime dependencies and remain
under their own licenses.

| Package | License | Notes |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | web framework |
| [Starlette](https://github.com/encode/starlette) | BSD-3-Clause | ASGI toolkit (FastAPI dependency) |
| [Uvicorn](https://github.com/encode/uvicorn) (`[standard]` extra) | BSD-3-Clause | ASGI server; extras: websockets (BSD-3-Clause), httptools (MIT), uvloop (MIT/Apache-2.0), watchfiles (MIT), python-dotenv (BSD-3-Clause) |
| [Pydantic](https://github.com/pydantic/pydantic) / pydantic-core | MIT | schema validation |
| [PyYAML](https://github.com/yaml/pyyaml) | MIT | YAML parsing |
| [python-can](https://github.com/hardbyte/python-can) | **LGPL-3.0-only** | CAN hardware abstraction; dependencies wrapt (BSD-2-Clause), packaging (Apache-2.0 OR BSD-2-Clause), typing_extensions (PSF-2.0) |

## python-can (LGPL-3.0)

udsbench uses python-can only through its public Python API and does not modify it. Installing
udsbench via `pip` keeps python-can as a separate, replaceable package, which satisfies the LGPL.

If you **redistribute a single-file build** (PyInstaller, `packaging/udsbench.spec`), python-can is
bundled into the executable. In that case you must ship the LGPL-3.0 license text with the build
(the spec file copies python-can's package metadata including its license into the bundle) and
make it possible for recipients to use a modified python-can, e.g. by also offering the regular
`pip install` distribution or the build files. When in doubt, distribute the wheel instead of a
single-file executable.

## Frontend

The browser UI has **no runtime dependencies**. Development tools (Vite, TypeScript, Vitest, jsdom,
ESLint, typescript-eslint, Prettier) are used only to build and test it; the built bundle contains
only udsbench's own code plus a small Vite module-preload helper (MIT).

## Standards and trademarks

ISO 14229 (UDS) and ISO 15765 (ISO-TP) are referenced by number only. udsbench does not contain
text from these standards; service, sub-function and NRC identifiers are the commonly used protocol
names. udsbench is not affiliated with, endorsed or certified by ISO or any vehicle or equipment
manufacturer. All trademarks belong to their respective owners.
