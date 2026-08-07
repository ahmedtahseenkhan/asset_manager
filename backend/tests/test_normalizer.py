"""Unit tests for the Normalizer."""
import pytest
from backend.normalizer.normalizer import Normalizer
from tests.conftest import make_raw


# ------------------------------------------------------------------ OS family


@pytest.mark.parametrize("os_name,os_ver,expected_family,expected_ver", [
    ("Windows 10",          "10.0.19041", "Windows",        "10"),
    ("Windows 11",          None,          "Windows",        "11"),
    ("Windows Server 2019", None,          "Windows Server", "2019"),
    ("Windows Server 2022", None,          "Windows Server", "2022"),
    ("Ubuntu 22.04",        "22.04",       "Linux",          "22.04"),
    ("Red Hat Enterprise",  "8.5",         "Linux",          "8.5"),
    ("linux",               None,          "Linux",          None),
    ("macOS",               "13.0",        "macOS",          "13.0"),
    ("Mac OS X",            "12.6",        "macOS",          "12.6"),
    (None,                  "10",          None,             "10"),
    ("UnknownOS",           "3.1",         None,             "3.1"),
])
def test_normalize_os(os_name, os_ver, expected_family, expected_ver):
    family, version = Normalizer._normalize_os(os_name, os_ver)
    assert family == expected_family
    assert version == expected_ver


# --------------------------------------------------------------- hostname


@pytest.mark.parametrize("raw,expected", [
    ("pc-001",              "PC-001"),
    ("PC-001.corp.local",   "PC-001"),
    ("server.sub.domain",   "SERVER"),
    (None,                  None),
    ("",                    None),
])
def test_normalize_hostname(raw, expected):
    assert Normalizer._normalize_hostname(raw) == expected


# --------------------------------------------------------------- full normalize


def test_normalize_returns_unified_record():
    raw = make_raw(
        hostname="ws-010.corp.local",
        fqdn="WS-010.Corp.Local",
        ip_addresses=["10.0.0.10", "10.0.0.10"],  # duplicate should be deduplicated
        mac_addresses=["aa:bb:cc:dd:ee:ff"],
        os_name="Windows 10",
        domain="Corp.Local",
    )
    result = Normalizer.normalize("ad", raw)

    assert result.hostname == "WS-010"          # uppercased, domain stripped
    assert result.fqdn == "ws-010.corp.local"   # lowercased
    assert result.domain == "corp.local"        # lowercased
    assert result.os_family == "Windows"
    assert result.os_version == "10"
    assert len(result.ip_addresses) == 1        # deduplicated
    assert result.mac_addresses == ["AA:BB:CC:DD:EE:FF"]  # uppercased
    assert result.status == "active"


def test_normalize_missing_optional_fields():
    raw = make_raw(hostname=None, fqdn=None, domain=None, os_name=None)
    result = Normalizer.normalize("crowdstrike", raw)
    assert result.hostname is None
    assert result.fqdn is None
    assert result.domain is None
    assert result.os_family is None
