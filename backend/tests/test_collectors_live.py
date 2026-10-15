"""
Collectors against real services. Skipped unless ITAM_LIVE_TESTS=1.

Start the services first (see docs/OPERATIONS.md, "Testing collectors"):
  SSH  : container on 127.0.0.1:2222, user scan / Scan-Pass-123 (NOPASSWD sudo for python3)
  SNMP : snmpd on 127.0.0.1:1161/udp, community "labro", v3 user v3user SHA/AES authpass123/privpass123
"""
import os

import asyncssh
import pytest

from backend.scanning.collectors import CollectorError, CredentialInput
from backend.scanning.collectors import snmp, ssh

pytestmark = pytest.mark.skipif(os.environ.get("ITAM_LIVE_TESTS") != "1", reason="set ITAM_LIVE_TESTS=1")


class _Keys:
    def __init__(self):
        self.store = {}

    async def lookup(self, host, port):
        return self.store.get((host, port))

    async def save(self, host, port, key):
        self.store[(host, port)] = key.export_public_key().decode()


SSH_OK = CredentialInput(1, "ssh_password", "scan", {"port": 2222, "sudo": "yes"}, {"password": "Scan-Pass-123"})


async def test_ssh_full_inventory_and_tofu():
    keys = _Keys()
    report = await ssh.collect("127.0.0.1", SSH_OK, keys.lookup, keys.save)
    assert report.hostname and report.software and report.local_accounts
    assert ("127.0.0.1", 2222) in keys.store            # trusted on first use
    await ssh.collect("127.0.0.1", SSH_OK, keys.lookup, keys.save)   # same key accepted


async def test_ssh_wrong_password_and_changed_key():
    keys = _Keys()
    wrong = CredentialInput(2, "ssh_password", "scan", {"port": 2222}, {"password": "nope"})
    with pytest.raises(CollectorError) as err:
        await ssh.collect("127.0.0.1", wrong, keys.lookup, keys.save)
    assert err.value.code == "auth_failed"
    keys.store[("127.0.0.1", 2222)] = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode()
    with pytest.raises(CollectorError) as err:
        await ssh.collect("127.0.0.1", SSH_OK, keys.lookup, keys.save)
    assert err.value.code == "host_key_changed"


async def test_snmp_v2c_and_v3():
    v2 = CredentialInput(1, "snmp_v2c", None, {}, {"community": "labro"})
    v3 = CredentialInput(2, "snmp_v3", "v3user",
                         {"security_level": "authPriv", "auth_protocol": "SHA", "priv_protocol": "AES128"},
                         {"auth_password": "authpass123", "priv_password": "privpass123"})
    for cred in (v2, v3):
        report = await snmp.collect("127.0.0.1", cred, port=1161)
        assert report.hostname and report.hardware.manufacturer == "Net-SNMP" and report.network_adapters


async def test_snmp_wrong_credentials():
    with pytest.raises(CollectorError) as err:
        await snmp.collect("127.0.0.1", CredentialInput(3, "snmp_v2c", None, {}, {"community": "x"}), port=1161)
    assert err.value.code == "snmp_no_response"
    bad_v3 = CredentialInput(4, "snmp_v3", "v3user",
                             {"security_level": "authPriv", "auth_protocol": "SHA", "priv_protocol": "AES128"},
                             {"auth_password": "WRONG-PASS", "priv_password": "privpass123"})
    with pytest.raises(CollectorError) as err:
        await snmp.collect("127.0.0.1", bad_v3, port=1161)
    assert err.value.code == "auth_failed"
