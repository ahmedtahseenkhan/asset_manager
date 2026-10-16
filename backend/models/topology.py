"""
Network topology read from switches and routers over SNMP (licence module:
topology). Each table holds the latest snapshot per collecting device.

- network_ports      interfaces of a switch/router (IF-MIB), with access VLAN
- network_neighbors  LLDP / CDP neighbours seen on those ports
- mac_locations      switch forwarding table: which MAC was learned on which port
- arp_entries        router ARP cache: IP ↔ MAC (gives MACs for hosts a scan
                     can't see at layer 2, e.g. from inside Docker)
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


def _switch_fk(nullable: bool = False):
    return Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=nullable, index=True)


class NetworkPort(Base):
    __tablename__ = "network_ports"

    id = Column(Integer, primary_key=True)
    device_id = _switch_fk()
    if_index = Column(Integer, nullable=False)
    name = Column(String(255))            # ifName (Gi1/0/12)
    description = Column(String(255))     # ifDescr
    alias = Column(String(255))           # ifAlias (admin's port label)
    mac = Column(String(32))
    speed_mbps = Column(Integer)
    oper_up = Column(Boolean)
    admin_up = Column(Boolean)
    vlan = Column(Integer)                # access VLAN (dot1qPvid)
    mac_count = Column(Integer, nullable=False, default=0)   # MACs learned on this port
    is_uplink = Column(Boolean, nullable=False, default=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "if_index", name="uq_network_port"),)


class NetworkNeighbor(Base):
    __tablename__ = "network_neighbors"

    id = Column(Integer, primary_key=True)
    device_id = _switch_fk()
    port_id = Column(Integer, ForeignKey("network_ports.id", ondelete="SET NULL"), index=True)
    local_port = Column(String(255))      # as the protocol reports it, if no port matched
    protocol = Column(String(8), nullable=False)          # lldp | cdp
    remote_chassis_id = Column(String(255))
    remote_port = Column(String(255))
    remote_port_desc = Column(String(255))
    remote_name = Column(String(255))
    remote_description = Column(String(500))
    remote_mgmt_ip = Column(String(64))
    remote_is_bridge = Column(Boolean)    # switch/router/AP vs phone/host
    remote_device_id = Column(Integer, ForeignKey("devices.id", ondelete="SET NULL"), index=True)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())


class MacLocation(Base):
    __tablename__ = "mac_locations"

    id = Column(Integer, primary_key=True)
    device_id = _switch_fk()
    port_id = Column(Integer, ForeignKey("network_ports.id", ondelete="CASCADE"), index=True)
    mac = Column(String(17), nullable=False)
    vlan = Column(Integer)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mac_locations_mac", "mac"),
        UniqueConstraint("device_id", "mac", "vlan", name="uq_mac_location"),
    )


class ArpEntry(Base):
    __tablename__ = "arp_entries"

    id = Column(Integer, primary_key=True)
    device_id = _switch_fk()              # the router/L3 switch that holds the cache
    ip = Column(String(45), nullable=False, index=True)
    mac = Column(String(17), nullable=False, index=True)
    if_index = Column(Integer)
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("device_id", "ip", name="uq_arp_entry"),)
