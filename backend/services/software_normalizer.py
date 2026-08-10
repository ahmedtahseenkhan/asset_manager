"""
Normalise raw software titles to a canonical product name for SAM matching.

Real SAM tools ship huge signature libraries; this is a pragmatic rules-based
normaliser: strip versions/editions/architecture noise and map common products.
"""
import re

_NOISE = re.compile(
    r"\b(\d+(\.\d+)+|x64|x86|64-bit|32-bit|\(?64-bit\)?|edition|version|v\d+|"
    r"20\d\d|r\d+|sp\d+|update|kb\d+|redistributable)\b",
    re.IGNORECASE,
)

# Canonical product aliases (substring -> product). Extend as needed.
_ALIASES = [
    ("microsoft office", "Microsoft Office"),
    ("office 365", "Microsoft 365"),
    ("microsoft 365", "Microsoft 365"),
    ("visual studio code", "Visual Studio Code"),
    ("visual studio", "Microsoft Visual Studio"),
    ("google chrome", "Google Chrome"),
    ("mozilla firefox", "Mozilla Firefox"),
    ("adobe acrobat", "Adobe Acrobat"),
    ("adobe photoshop", "Adobe Photoshop"),
    ("7-zip", "7-Zip"),
    ("zoom", "Zoom"),
    ("slack", "Slack"),
    ("docker", "Docker"),
    ("python", "Python"),
    ("node", "Node.js"),
    ("java", "Java"),
    ("windows 11", "Windows 11"),
    ("windows 10", "Windows 10"),
    ("sql server", "Microsoft SQL Server"),
]


def normalize_software(name: str) -> str:
    if not name:
        return ""
    low = name.lower()
    for needle, product in _ALIASES:
        if needle in low:
            return product
    # Generic cleanup: drop noise tokens, collapse whitespace, title-case.
    cleaned = _NOISE.sub("", name)
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned).strip(" -_")
    return cleaned or name.strip()
