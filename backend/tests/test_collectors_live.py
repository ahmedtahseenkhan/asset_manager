"""
Collectors against real services. Skipped unless ITAM_LIVE_TESTS=1.

Start the services first (see docs/OPERATIONS.md, "Testing collectors"):
  SSH  : container on 127.0.0.1:2222, user scan / Scan-Pass-123 (NOPASSWD sudo for python3)
  SNMP : snmpd on 127.0.0.1:1161/udp, community "labro", v3 user v3user SHA/AES authpass123/privpass123
  SIM  : snmpsim on 127.0.0.1:1170/udp with tests/live/snmpsim recordings (topology)
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


def _sim(community):
    return CredentialInput(9, "snmp_v2c", None, {"port": 1170}, {"community": community})


async def test_topology_from_recorded_switches():
    from backend.topology import snmp_topology
    access = await snmp_topology.collect("127.0.0.1", _sim("access"))
    assert {p.name: p.vlan for p in access.ports}["Gi1/0/12"] == 20
    nbrs = {n.sys_name: n for n in access.neighbors}
    assert nbrs["core-sw.corp.local"].local_if_index == 10148 and nbrs["core-sw.corp.local"].is_bridge
    assert nbrs["SEP0004F2000005"].is_bridge is False
    assert ("AA:00:00:00:00:12", 10112, 20) in {(f.mac, f.if_index, f.vlan) for f in access.fdb}

    router = await snmp_topology.collect("127.0.0.1", _sim("router"))
    assert router.neighbors[0].protocol == "cdp" and router.neighbors[0].mgmt_ip == "10.0.0.1"
    assert ("10.20.0.12", "AA:00:00:00:00:12") in {(a.ip, a.mac) for a in router.arp}

    legacy = await snmp_topology.collect("127.0.0.1", _sim("legacy"))     # per-VLAN via community@vlan
    assert {(f.mac, f.vlan) for f in legacy.fdb} == {("BB:00:00:00:00:10", 10), ("BB:00:00:00:00:20", 20)}
