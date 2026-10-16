"""
Normalise raw software titles: canonical product, publisher and category.

Driven by the bundled software catalogue (lifecycle/software_catalog.json):
the first product pattern that matches the installed title wins. Titles the
catalogue doesn't know keep a cleaned-up name and the cleaned publisher, with
no category. The product name is what SAM matches entitlements against.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

CATALOG_PATH = Path(__file__).resolve().parent.parent / "lifecycle" / "software_catalog.json"

_NOISE = re.compile(
    r"\b(\d+(\.\d+)+|x64|x86|64-bit|32-bit|\(?64-bit\)?|edition|version|v\d+|"
    r"20\d\d|r\d+|sp\d+|update|kb\d+|redistributable)\b",
    re.IGNORECASE,
)
# Legal-form suffixes dropped from publishers: "Foo Software GmbH" -> "Foo Software"
_SUFFIX = re.compile(
    r"[,.\s]+(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|ag|s\.?a|b\.?v|"
    r"pty( ltd)?|plc|s\.?r\.?l|kg|oy|ab|as|aps|s\.r\.o|sp\. z o\.o)\.?$",
    re.IGNORECASE,
)
_MARKS = re.compile(r"\s*(\(r\)|\(tm\)|®|™)\s*", re.IGNORECASE)
# Not publishers: macOS "obtained from" values sent by agents before 2.1
_NOT_PUBLISHERS = {"unknown", "identified_developer", "mac_app_store", "n/a", "none", "(none)"}


@dataclass(frozen=True)
class SoftwareClass:
    product: str
    publisher: Optional[str]
    category: Optional[str]


class _Fmt(dict):
    def __missing__(self, key):        # an unmatched optional group formats as ""
        return ""


def _load():
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = [(re.compile(p["match"], re.IGNORECASE), p["product"], p.get("publisher"), p.get("category"),
                 re.compile(p["publisher_match"], re.IGNORECASE) if p.get("publisher_match") else None)
                for p in data["products"]]
    publishers = [(re.compile(p["match"], re.IGNORECASE), p["name"]) for p in data["publishers"]]
    return data, products, publishers


_DATA, _PRODUCTS, _PUBLISHERS = _load()
CATEGORIES: List[str] = list(_DATA["categories"])
HIDDEN_BY_DEFAULT: List[str] = list(_DATA.get("hidden_by_default", []))
CATALOG_VERSION: str = _DATA["version"]


def normalize_publisher(publisher: Optional[str]) -> Optional[str]:
    if not publisher or not publisher.strip() or publisher.strip().lower() in _NOT_PUBLISHERS:
        return None
    raw = _MARKS.sub(" ", publisher).strip()
    for rx, name in _PUBLISHERS:
        if rx.search(raw):
            return name
    cleaned = raw
    for _ in range(2):                  # "Foo Pty Ltd." -> "Foo"
        cleaned = _SUFFIX.sub("", cleaned).strip(" ,.")
    return (cleaned or raw)[:255]


def _clean_title(name: str) -> str:
    cleaned = _NOISE.sub("", name)
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned).strip(" -_")
    return cleaned or name.strip()


def classify_software(name: str, publisher: Optional[str] = None) -> SoftwareClass:
    if not name:
        return SoftwareClass("", normalize_publisher(publisher), None)
    pub = normalize_publisher(publisher)
    for rx, product, prod_pub, category, pub_rx in _PRODUCTS:
        m = rx.search(name)
        if not m or (pub_rx and not pub_rx.search((publisher or "").strip())):
            continue
        values = _Fmt({k: v for k, v in m.groupdict().items() if v})
        values["publisher"] = pub or ""
        values["title"] = _clean_title(name)
        fmt = lambda s: re.sub(r"\{0\}", m.group(0).strip().replace("{", "").replace("}", ""), s)  # noqa: E731
        product_name = fmt(product).format_map(values).strip() or _clean_title(name)
        publisher_name = fmt(prod_pub).format_map(values).strip() if prod_pub else ""
        return SoftwareClass(product_name[:500], (publisher_name or pub or None), category)
    return SoftwareClass(_clean_title(name)[:500], pub, None)


def normalize_software(name: str) -> str:
    """Canonical product name (SAM matching key)."""
    return classify_software(name).product if name else ""


def classify_many(pairs: List[Tuple[str, Optional[str]]]) -> List[SoftwareClass]:
    return [classify_software(n, p) for n, p in pairs]
