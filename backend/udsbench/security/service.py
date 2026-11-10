"""Generischer SecurityAccess-Ablauf (0x27) und datengetriebene NRC-Testsuite."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.schema import SecurityLevelDef, SecurityNrcCase
from ..core.errors import NotFoundError, ProviderError
from ..core.hexutil import to_hex
from ..testrunner.models import TestDef
from .providers import PROVIDER_TYPES, SeedKeyProvider, create_provider

if TYPE_CHECKING:
    from ..core.platform import Platform

audit = logging.getLogger("udsbench.audit.security")


class SecurityService:
    def __init__(self, platform: Platform, providers_dir: Path) -> None:
        self.platform = platform
        self.providers_dir = providers_dir
        self._cache: dict[str, SeedKeyProvider] = {}
        self.mask = True

    def invalidate(self) -> None:
        self._cache.clear()

    # Provider -------------------------------------------------------------------------------
    def provider(self, ref: str | None) -> SeedKeyProvider:
        ref = ref or "demo"
        if ref in self._cache:
            return self._cache[ref]
        defs = self.platform.packages.merged.providers
        if ref in defs:
            d = defs[ref]
            prov = create_provider(d.id, d.type, d.params, self.providers_dir)
        elif ref in PROVIDER_TYPES:
            prov = create_provider(ref, ref, {}, self.providers_dir)
        else:
            raise NotFoundError(f"Security-Provider {ref!r} nicht gefunden")
        self._cache[ref] = prov
        return prov

    def list_providers(self) -> list[dict[str, Any]]:
        out = []
        for pid, d in self.platform.packages.merged.providers.items():
            entry = self.provider(pid).describe()
            entry["description"] = d.description
            out.append(entry)
        return out

    def level_def(self, ecu: str | None, level: int) -> SecurityLevelDef | None:
        rt_def = self.platform.packages.merged.ecus.get(ecu or "")
        if rt_def is None:
            return None
        return next((lv for lv in rt_def.ecu.security_levels if lv.level == level), None)

    async def compute_key(
        self,
        ecu: str | None,
        level: int,
        seed: bytes,
        *,
        provider: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        ldef = self.level_def(ecu, level)
        prov_ref = provider or (ldef.provider if ldef else None)
        prov = self.provider(prov_ref)
        merged = dict(ldef.params) if ldef and not provider else {}
        merged.update(params or {})
        try:
            key = await prov.compute_key_async(seed, level, merged)
        except ProviderError:
            audit.warning(
                "Key-Berechnung fehlgeschlagen (ECU %s, Level 0x%02X, Provider %s)",
                ecu,
                level,
                prov.id,
                extra={"ecu": ecu, "level": level, "provider": prov.id},
            )
            raise
        except Exception as exc:
            audit.warning("Key-Berechnung fehlgeschlagen: %s", exc, extra={"ecu": ecu, "level": level})
            raise ProviderError(f"Key-Berechnung fehlgeschlagen: {exc}") from exc
        audit.info(
            "Key berechnet (ECU %s, Level 0x%02X, Provider %s, Seed-Länge %d, Key-Länge %d)",
            ecu,
            level,
            prov.id,
            len(seed),
            len(key),
            extra={"ecu": ecu, "level": level, "provider": prov.id},
        )
        return key

    # Ablauf ---------------------------------------------------------------------------------
    async def request_seed(self, ecu: str, level: int) -> dict[str, Any]:
        rt = self.platform.diag.get(ecu)
        res = await rt.request(bytes([0x27, level]))
        audit.info(
            "Seed angefordert: ECU %s Level 0x%02X → %s",
            rt.id,
            level,
            "positiv" if res.positive else (f"NRC 0x{res.nrc:02X}" if res.nrc is not None else res.error),
            extra={"ecu": rt.id, "level": level, "nrc": res.nrc},
        )
        seed = res.data[1:] if res.positive else None
        return {
            "result": res.to_dict(),
            "seed": to_hex(seed) if seed is not None else None,
            "already_unlocked": bool(seed is not None and len(seed) > 0 and not any(seed)),
        }

    async def send_key(self, ecu: str, level: int, key: bytes) -> dict[str, Any]:
        rt = self.platform.diag.get(ecu)
        res = await rt.request(bytes([0x27, level + 1]) + key)
        audit.info(
            "Key gesendet: ECU %s Level 0x%02X → %s",
            rt.id,
            level,
            "ENTSPERRT" if res.positive else (f"NRC 0x{res.nrc:02X}" if res.nrc is not None else res.error),
            extra={"ecu": rt.id, "level": level, "nrc": res.nrc, "unlocked": res.positive},
        )
        return {"result": res.to_dict(), "unlocked": res.positive}

    async def unlock(
        self,
        ecu: str,
        level: int,
        *,
        provider: str | None = None,
        params: dict[str, Any] | None = None,
        switch_session: bool = True,
    ) -> dict[str, Any]:
        rt = self.platform.diag.get(ecu)
        steps: list[dict[str, Any]] = []
        ldef = self.level_def(rt.id, level)
        audit.info("Unlock-Versuch: ECU %s Level 0x%02X", rt.id, level, extra={"ecu": rt.id, "level": level})
        if switch_session and ldef and ldef.session is not None and rt.session != ldef.session:
            r = await rt.request(bytes([0x10, ldef.session]))
            steps.append({"step": "session", "result": r.to_dict()})
            if not r.positive:
                return {
                    "unlocked": False,
                    "message": "Sessionwechsel fehlgeschlagen",
                    "steps": steps,
                    "_last": r,
                }
        seed_res = await rt.request(bytes([0x27, level]))
        steps.append({"step": "request_seed", "result": _masked(seed_res.to_dict())})
        if not seed_res.positive:
            msg = f"Seed-Anforderung abgelehnt: {seed_res.decoded.get('text') or seed_res.error}"
            audit.warning("Unlock fehlgeschlagen: %s", msg, extra={"ecu": rt.id, "level": level})
            return {"unlocked": False, "message": msg, "steps": steps, "_last": seed_res}
        seed = seed_res.data[1:]
        if seed and not any(seed):
            audit.info("ECU %s Level 0x%02X war bereits entsperrt (Seed = 0)", rt.id, level)
            return {
                "unlocked": True,
                "message": "bereits entsperrt (Seed = 0)",
                "steps": steps,
                "_last": seed_res,
            }
        key = await self.compute_key(rt.id, level, seed, provider=provider, params=params)
        key_res = await rt.request(bytes([0x27, level + 1]) + key)
        steps.append({"step": "send_key", "result": _masked(key_res.to_dict())})
        ok = key_res.positive
        msg = "entsperrt" if ok else f"Key abgelehnt: {key_res.decoded.get('text') or key_res.error}"
        audit.log(
            logging.INFO if ok else logging.WARNING,
            "Unlock %s: ECU %s Level 0x%02X – %s",
            "erfolgreich" if ok else "fehlgeschlagen",
            rt.id,
            level,
            msg,
            extra={"ecu": rt.id, "level": level, "unlocked": ok, "nrc": key_res.nrc},
        )
        return {"unlocked": ok, "message": msg, "steps": steps, "_last": key_res}

    # NRC-Testsuite --------------------------------------------------------------------------
    def nrc_cases(self, ecu: str, level: int, options: dict[str, Any] | None = None) -> list[TestDef]:
        """Erzeugt datengetriebene Provokationstests (überschreibbar per ECU-Konfiguration)."""
        o = dict(options or {})
        rdef = self.platform.packages.merged.ecus.get(ecu)
        if rdef is None:
            raise NotFoundError(f"ECU {ecu!r} unbekannt")
        ldef = self.level_def(ecu, level)
        session = o.get("session", ldef.session if ldef and ldef.session is not None else 0x03)
        configured = {lv.level for lv in rdef.ecu.security_levels}
        unsupported = o.get("unsupported_level") or next(
            (lv for lv in range(0x01, 0x42, 2) if lv not in configured and lv != level), 0x41
        )
        max_attempts = int(o.get("max_attempts", 3))
        L, K = level, level + 1
        enter = [{"session": 0x01, "expect": {}}, {"session": session}]
        leave = [{"session": 0x01, "expect": {}}]
        bad_key = "${invert(key)}"
        defaults: list[dict[str, Any]] = [
            {
                "id": "positive_reference",
                "name": "Positiver Referenzfall (gültiger Key)",
                "expected_nrc": None,
                "steps": [
                    {"request_seed": L, "expect": {"positive": True}},
                    {"compute_key": {"level": L}},
                    {"send": {"payload": f"27 {K:02X} ${{key}}"}, "expect": {"positive": True}},
                ],
            },
            {
                "id": "invalid_key",
                "name": "Ungültiger Key",
                "expected_nrc": 0x35,
                "steps": [
                    {"request_seed": L},
                    {"compute_key": {"level": L}},
                    {"send": {"payload": f"27 {K:02X} {bad_key}"}, "expect": {"nrc": 0x35}},
                ],
            },
            {
                "id": "wrong_length",
                "name": "Falsches Format / falsche Länge (Key zu lang)",
                "expected_nrc": 0x13,
                "steps": [
                    {"request_seed": L},
                    {"compute_key": {"level": L}},
                    {"send": {"payload": f"27 {K:02X} ${{key}} 00"}, "expect": {"nrc": 0x13}},
                ],
            },
            {
                "id": "unsupported_subfunction",
                "name": f"Nicht unterstützte Subfunktion (0x{unsupported:02X})",
                "expected_nrc": 0x12,
                "steps": [{"send": {"payload": f"27 {unsupported:02X}"}, "expect": {"nrc": 0x12}}],
            },
            {
                "id": "key_without_seed",
                "name": "Key ohne vorherigen Seed (Sequenzfehler)",
                "expected_nrc": 0x24,
                "steps": [
                    {
                        "send": {"payload": f"27 {K:02X} " + " ".join(["00"] * int(o.get("key_length", 4)))},
                        "expect": {"nrc": 0x24},
                    }
                ],
            },
            {
                "id": "out_of_range",
                "name": "Wert außerhalb Bereich (ungültiger securityAccessDataRecord)",
                "expected_nrc": 0x31,
                "steps": [
                    {
                        "send": {"payload": o.get("out_of_range_request", f"27 {L:02X} FF FF")},
                        "expect": {"nrc": 0x31},
                    }
                ],
            },
            {
                "id": "conditions_not_correct",
                "name": "Zugriff verweigert / Bedingungen nicht erfüllt (DefaultSession)",
                "expected_nrc": [0x7F, 0x22, 0x33, 0x7E],
                "skip_enter": True,
                "steps": [
                    {"session": 0x01, "expect": {}},
                    {"send": {"payload": f"27 {L:02X}"}, "expect": {"nrc": [0x7F, 0x22, 0x33, 0x7E]}},
                ],
            },
            {
                "id": "service_not_supported",
                "name": "Dienst nicht unterstützt (ISO-reservierte SID)",
                "expected_nrc": 0x11,
                "steps": [
                    {"send": {"payload": o.get("unsupported_request", "3F 00")}, "expect": {"nrc": 0x11}}
                ],
            },
            {
                "id": "exceed_attempts",
                "name": f"Fehlversuchssperre ({max_attempts} ungültige Keys)",
                "expected_nrc": 0x36,
                "steps": [
                    {
                        "repeat": {
                            "count": max_attempts - 1,
                            "steps": [
                                {"request_seed": L},
                                {"compute_key": {"level": L}},
                                {"send": {"payload": f"27 {K:02X} {bad_key}"}, "expect": {"nrc": 0x35}},
                            ],
                        }
                    },
                    {"request_seed": L},
                    {"compute_key": {"level": L}},
                    {"send": {"payload": f"27 {K:02X} {bad_key}"}, "expect": {"nrc": 0x36}},
                ],
            },
            {
                "id": "time_delay",
                "name": "Zeitsperre aktiv (requiredTimeDelayNotExpired)",
                "expected_nrc": 0x37,
                "steps": [{"send": {"payload": f"27 {L:02X}"}, "expect": {"nrc": 0x37}}],
            },
        ]
        # Reihenfolge: Der positive Referenzfall setzt den Fehlversuchszähler zurück, bevor die Sperre
        # provoziert wird; die Zeitsperre folgt unmittelbar auf die Fehlversuchssperre.
        order = [
            "invalid_key",
            "wrong_length",
            "unsupported_subfunction",
            "key_without_seed",
            "out_of_range",
            "conditions_not_correct",
            "service_not_supported",
            "positive_reference",
            "exceed_attempts",
            "time_delay",
        ]
        defaults.sort(key=lambda c: order.index(c["id"]))
        overrides: dict[str, SecurityNrcCase] = {c.id: c for c in (rdef.ecu.security_nrc_cases or [])}
        tests: list[TestDef] = []
        for case in defaults:
            ov = overrides.pop(case["id"], None)
            if ov is not None:
                if not ov.enabled:
                    continue
                case = {**case, "name": ov.name or case["name"]}
                if ov.expected_nrc is not None:
                    case["steps"] = _replace_expected(case["steps"], case["expected_nrc"], ov.expected_nrc)
                    case["expected_nrc"] = ov.expected_nrc
                if ov.steps is not None:
                    case["steps"] = ov.steps
            tests.append(self._case_test(ecu, L, case, enter, leave))
        for ov in overrides.values():
            if ov.enabled and ov.steps:
                tests.append(
                    self._case_test(
                        ecu,
                        L,
                        {"id": ov.id, "name": ov.name, "expected_nrc": ov.expected_nrc, "steps": ov.steps},
                        enter,
                        leave,
                    )
                )
        return tests

    def _case_test(
        self,
        ecu: str,
        level: int,
        case: dict[str, Any],
        enter: list[dict[str, Any]],
        leave: list[dict[str, Any]],
    ) -> TestDef:
        exp = case.get("expected_nrc")
        if isinstance(exp, list):
            exp_txt = "/".join(f"0x{x:02X}" if isinstance(x, int) else str(x) for x in exp)
        else:
            exp_txt = f"0x{exp:02X}" if isinstance(exp, int) else (str(exp) if exp else "positiv")
        return TestDef.model_validate(
            {
                "id": f"security_nrc.{case['id']}",
                "name": case["name"],
                "description": f"Erwartet: {exp_txt}",
                "ecu": ecu,
                "tags": ["security", "nrc"],
                "vars": {"level": level},
                "setup": [] if case.get("skip_enter") else enter,
                "steps": case["steps"],
                "teardown": leave,
            }
        )


def _replace_expected(steps: list[dict[str, Any]], old: Any, new: Any) -> list[dict[str, Any]]:
    out = []
    for s in steps:
        s = dict(s)
        if isinstance(s.get("expect"), dict) and s["expect"].get("nrc") == old:
            s["expect"] = {**s["expect"], "nrc": new}
        out.append(s)
    return out


def _masked(d: dict[str, Any]) -> dict[str, Any]:
    from ..logs.setup import get_masker

    if not get_masker().enabled:
        return d
    d = dict(d)
    for k in ("request", "response"):
        if d.get(k) and len(d[k]) > 6:
            d[k] = d[k][:5] + " ***"
    if d.get("decoded", {}).get("fields", {}).get("seed"):
        d["decoded"] = {**d["decoded"], "fields": {**d["decoded"]["fields"], "seed": "***"}}
    return d
