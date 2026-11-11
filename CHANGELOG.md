# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Connecting real hardware after `udsbench run --demo` failed with "channel 'default' is already
  connected". *Connect* now switches an existing channel to the new settings
  (`POST /connection?replace=true`) and keeps the previous connection if the new one cannot be opened.
- PCAN: connecting with CAN FD failed because python-can ignores `bitrate`/`data_bitrate` for
  `pcan`; udsbench now computes the bit timing for the 80 MHz PCAN clock.
- Connection view: switching the interface pre-fills the matching channel (e.g. `PCAN_USBBUS1`
  instead of `can0`); new *Detect* button lists connected adapters.
- Clear error messages with hints when a CAN interface cannot be opened (unknown PCAN channel,
  missing PCAN-Basic library, socketcan interface down).

### Changed
- The built browser UI (`backend/udsbench/static/`) is now committed, so udsbench can be installed
  and built (`pip install .`, wheel, PyInstaller) without Node.js/npm. CI verifies that the
  committed build matches the frontend sources.

## [0.1.0] – 2026-11-10

First public preview.

### Added
- ISO-TP transport (ISO 15765-2) with normal/extended/mixed addressing, 11/29-bit IDs, CAN-FD,
  configurable padding and DLC mode, flow control, STmin (incl. µs), timeouts.
- UDS client (ISO 14229-1/-2): P2/P2* handling, response pending (0x78), SPRMIB, functional
  requests, TesterPresent/S3, session and security state; service catalogue and full NRC table.
- CAN abstraction: built-in virtual bus and python-can adapter; multiple channels.
- Configuration packages (YAML/JSON) with schema validation and collision detection; neutral demo
  package and template; AI assistant prompt to create packages from specifications.
- Simulated ECU (test double) for hardware-free operation and conformance tests.
- Messages, sequences, declarative tests and suites; reports as JSON, JUnit XML, HTML and ZIP;
  time-range reports with attached traces and logs.
- Generic security access with exchangeable seed-to-key providers (native library, script,
  Python, plugin, demo) and a negative-response test suite.
- Live trace, recording/replay (JSONL, CSV, ASC, candump), timechart with event track,
  dashboards with custom buttons.
- REST/WebSocket API with OpenAPI, token authentication, structured JSON-lines logging with
  correlation IDs and secret masking.
- Browser UI (German) with searchable, context-sensitive help.
