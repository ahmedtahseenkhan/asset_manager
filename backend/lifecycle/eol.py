"""
End-of-life matching: which OS release or software version a device runs, and
until when its vendor supports it.

The catalogue (eol_catalog.json) ships with each release and works offline. An
administrator can upload a newer one between releases; the newest by
publication date wins. Identification strategies live here, dates live in the
catalogue, so a catalogue update can add releases (a new Windows build, Ubuntu
version, Office year) without a code change.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BUNDLED_PATH = Path(__file__).with_name("eol_catalog.json")
ENDING_SOON_DAYS = 180
STATUSES = ("unsupported", "ending_soon", "supported")
_MATCHERS = ("windows", "os-version", "software")


@dataclass(frozen=True)
class EolMatch:
    kind: str                       # os | software
    product_id: str
    product: str                    # "Windows 10"
    cycle: str                      # "22H2"
    title: str                      # "Windows 10 22H2 (Enterprise/Education)"
    eol: Optional[date]             # None: supported, no end announced
    support_end: Optional[date] = None
    extended: Optional[date] = None


def status(eol: Optional[date], today: Optional[date] = None) -> str:
    if eol is None:
        return "supported"
    today = today or date.today()
    if eol < today:
        return "unsupported"
    return "ending_soon" if (eol - today).days <= ENDING_SOON_DAYS else "supported"


def _date(value: Any, where: str) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: {value!r} is not a YYYY-MM-DD date")


def _regex(value: Optional[str], where: str) -> Optional[re.Pattern]:
    if not value:
        return None
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{where}: invalid pattern ({exc})")


@dataclass
class _Cycle:
    cycle: str
    label: Optional[str]
    eol: Optional[date]
    support_end: Optional[date]
    extended: Optional[date]
    eol_enterprise: Optional[date]
    eol_iot: Optional[date]
    build: Optional[int]
    edition: Optional[str]          # "ltsc" for Windows LTSC/LTSB
    server: bool
    os_regex: Optional[re.Pattern]


@dataclass
class _Product:
    id: str
    name: str
    kind: str
    match: str
    source: Optional[str]
    os_regex: Optional[re.Pattern]
    name_regex: Optional[re.Pattern]
    version_regex: Optional[re.Pattern]
    cycles: List[_Cycle]
    by_cycle: Dict[str, _Cycle]


_VERSION = re.compile(r"\d+(?:\.\d+)*")


def _windows_build(*values: Optional[str]) -> Optional[int]:
    """22631 from "22631.4317", "10.0.22631" or AD's "10.0 (19045)"."""
    for value in values:
        for n in re.findall(r"\d+", str(value or "")):
            if 2000 <= int(n) < 100000:
                return int(n)
    return None


class Catalog:
    def __init__(self, data: Dict[str, Any]):
        """Parse and validate. Raises ValueError with a message an admin can act on."""
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError("Not an end-of-life catalogue (expected \"schema\": 1)")
        self.version = str(data.get("version") or "").strip()
        if not self.version or len(self.version) > 32:
            raise ValueError("\"version\" is required (at most 32 characters)")
        self.published = _date(data.get("published"), "published")
        if self.published is None:
            raise ValueError("\"published\" is required")
        products = data.get("products")
        if not isinstance(products, list) or not products:
            raise ValueError("\"products\" must be a non-empty list")

        self.products: List[_Product] = []
        seen = set()
        for i, p in enumerate(products):
            where = f"products[{i}]"
            if not isinstance(p, dict):
                raise ValueError(f"{where}: must be an object")
            pid, name = str(p.get("id") or ""), str(p.get("name") or "")
            if not pid or not name or len(pid) > 64 or len(name) > 128:
                raise ValueError(f"{where}: \"id\" and \"name\" are required")
            if pid in seen:
                raise ValueError(f"{where}: duplicate id {pid!r}")
            seen.add(pid)
            where = f"product {pid!r}"
            kind, match = p.get("kind"), p.get("match")
            if kind not in ("os", "software"):
                raise ValueError(f"{where}: \"kind\" must be os or software")
            if match not in _MATCHERS:
                raise ValueError(f"{where}: \"match\" must be one of {', '.join(_MATCHERS)}")
            prod = _Product(
                id=pid, name=name, kind=kind, match=match, source=p.get("source"),
                os_regex=_regex(p.get("os_regex"), where), name_regex=_regex(p.get("name_regex"), where),
                version_regex=_regex(p.get("version_regex"), where), cycles=[], by_cycle={})
            if match == "os-version" and not prod.os_regex:
                raise ValueError(f"{where}: \"os_regex\" is required")
            if match == "software" and not prod.name_regex:
                raise ValueError(f"{where}: \"name_regex\" is required")
            cycles = p.get("cycles")
            if not isinstance(cycles, list) or not cycles:
                raise ValueError(f"{where}: \"cycles\" must be a non-empty list")
            for c in cycles:
                cname = str((c or {}).get("cycle") or "")
                if not cname or len(cname) > 64:
                    raise ValueError(f"{where}: every cycle needs a \"cycle\"")
                cw = f"{where} cycle {cname!r}"
                if "eol" not in c:
                    raise ValueError(f"{cw}: \"eol\" is required (null if no end is announced)")
                build = c.get("build")
                if build is not None and not isinstance(build, int):
                    raise ValueError(f"{cw}: \"build\" must be a number")
                cyc = _Cycle(
                    cycle=cname, label=c.get("label"), eol=_date(c.get("eol"), cw),
                    support_end=_date(c.get("support_end"), cw), extended=_date(c.get("extended"), cw),
                    eol_enterprise=_date(c.get("eol_enterprise"), cw), eol_iot=_date(c.get("eol_iot"), cw),
                    build=build, edition=c.get("edition"), server=bool(c.get("server")),
                    os_regex=_regex(c.get("os_regex"), cw))
                if match == "windows" and cyc.build is None and cyc.os_regex is None:
                    raise ValueError(f"{cw}: Windows cycles need \"build\" or \"os_regex\"")
                prod.cycles.append(cyc)
                prod.by_cycle.setdefault(cname.lower(), cyc)
            self.products.append(prod)

    @classmethod
    def bundled(cls) -> "Catalog":
        return cls(json.loads(BUNDLED_PATH.read_text(encoding="utf-8")))

    @property
    def sort_key(self) -> Tuple[date, str]:
        return self.published, self.version

    def summary(self) -> Dict[str, Any]:
        return {"version": self.version, "published": self.published.isoformat(),
                "products": [{"id": p.id, "name": p.name, "kind": p.kind, "source": p.source,
                              "cycles": [{"cycle": c.cycle, "label": c.label, "eol": c.eol,
                                          "eol_enterprise": c.eol_enterprise, "eol_iot": c.eol_iot,
                                          "support_end": c.support_end, "extended": c.extended}
                                         for c in p.cycles]}
                             for p in self.products]}

    # ── OS ──────────────────────────────────────────────────────────────────
    def match_os(self, os_name: Optional[str], os_version: Optional[str] = None,
                 os_build: Optional[str] = None) -> Optional[EolMatch]:
        name = (os_name or "").strip()
        if not name:
            return None
        if re.search(r"windows", name, re.IGNORECASE):
            return self._match_windows(name, _windows_build(os_build, os_version))
        for p in self.products:
            if p.match == "os-version" and p.os_regex.search(name):
                version = (os_version or "").strip() or next(iter(_VERSION.findall(name)), "")
                parts = _VERSION.match(version)
                if not parts:
                    return None
                nums = parts.group(0).split(".")
                for n in (2, 1):                      # "10.15" before "10", "22.04" before "22"
                    c = p.by_cycle.get(".".join(nums[:n]).lower()) if len(nums) >= n else None
                    if c:
                        return self._result(p, c, c.eol)
                return None
        return None

    def _match_windows(self, name: str, build: Optional[int]) -> Optional[EolMatch]:
        low = name.lower()
        server = "server" in low
        ltsc = bool(re.search(r"\blts[bc]\b", low))
        iot = "iot" in low
        enterprise = bool(re.search(r"\b(enterprise|education)\b", low)) and "pro education" not in low
        candidates = [(p, c) for p in self.products if p.match == "windows" for c in p.cycles
                      if c.server == server]
        hit = next(((p, c) for p, c in candidates if c.os_regex and c.os_regex.search(name)), None)
        if hit is None and build:
            same_build = [(p, c) for p, c in candidates if c.build == build]
            hit = next(((p, c) for p, c in same_build if (c.edition == "ltsc") == ltsc), None) \
                or next(iter(same_build), None)
        if hit is None:
            return None
        p, c = hit
        eol, note = c.eol, None
        if c.edition == "ltsc":
            if iot and c.eol_iot:
                eol, note = c.eol_iot, "IoT"
        elif c.eol_enterprise:
            eol, note = (c.eol_enterprise, "Enterprise/Education") if enterprise else (c.eol, "Home/Pro")
        return self._result(p, c, eol, note)

    # ── software ────────────────────────────────────────────────────────────
    def match_software(self, name: Optional[str], version: Optional[str] = None) -> Optional[EolMatch]:
        if not name:
            return None
        for p in self.products:
            if p.match != "software":
                continue
            m = p.name_regex.search(name)
            if not m:
                continue
            cycle = m.groupdict().get("cycle")
            if cycle is None and p.version_regex:
                vm = p.version_regex.search(version or "")
                cycle = vm.groupdict().get("cycle") if vm else None
            c = p.by_cycle.get((cycle or "*").lower())
            return self._result(p, c, c.eol) if c else None
        return None

    @staticmethod
    def _result(p: _Product, c: _Cycle, eol: Optional[date], note: Optional[str] = None) -> EolMatch:
        title = c.label or (p.name if c.cycle == "*" else f"{p.name} {c.cycle}")
        if note:
            title = f"{title} ({note})"
        return EolMatch(kind=p.kind, product_id=p.id, product=p.name, cycle=c.cycle, title=title[:255],
                        eol=eol, support_end=c.support_end, extended=c.extended)


# The catalogue in effect: the bundled one, or a newer uploaded one (see LifecycleService).
_current: Catalog = Catalog.bundled()


def current() -> Catalog:
    return _current


def use(catalog: Catalog) -> None:
    global _current
    _current = catalog
