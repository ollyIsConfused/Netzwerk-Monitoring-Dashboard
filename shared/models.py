"""ORM models for the network monitoring dashboard.

Shared between the FastAPI backend (reads/writes config, serves data) and the
collector service (writes metrics, raises alerts).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.orm import relationship

from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class DeviceType(str, enum.Enum):
    switch = "switch"
    router = "router"
    dns_server = "dns_server"
    webserver = "webserver"
    nas = "nas"
    other = "other"
    # Spaeter dazugekommen - in bestehenden PostgreSQL-Datenbanken ergaenzt sie
    # add_missing_enum_values() automatisch
    gateway = "gateway"
    dhcp_server = "dhcp_server"
    workstation = "workstation"


class MetricStatus(str, enum.Enum):
    ok = "ok"
    warning = "warning"
    critical = "critical"
    unknown = "unknown"


class AlertLevel(str, enum.Enum):
    warning = "warning"
    critical = "critical"
    recovered = "recovered"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.viewer)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Nach Erstanlage oder einem vom Admin gesetzten (Einmal-)Passwort: bis zum eigenen
    # Passwort erlaubt die Anmeldung nur das Aendern des Passworts
    must_change_password = Column(Boolean, default=False, nullable=False, server_default=false())
    # Letzte "Passwort vergessen"-Anfrage - Hinweis in der Benutzerverwaltung und Sperrfrist fuer Mails
    password_reset_requested_at = Column(DateTime, nullable=True)
    # Wird bei jedem neuen Passwort erhoeht; Tokens mit aelterer Version (andere Sitzungen) gelten nicht mehr
    token_version = Column(Integer, default=0, nullable=False, server_default="0")


class Vlan(Base):
    __tablename__ = "vlans"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    tag = Column(Integer, unique=True, nullable=False)
    description = Column(Text, nullable=True)

    devices = relationship("Device", back_populates="vlan")


class DeviceTaggedVlan(Base):
    """Trunk-Port: ein VLAN, das ein Geraet getaggt fuehrt (das native VLAN steht in devices.vlan_id),
    optional mit der Adresse des Geraets in diesem VLAN - beim Router z. B. das Gateway 192.168.20.1."""

    __tablename__ = "device_tagged_vlans"

    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True)
    vlan_id = Column(Integer, ForeignKey("vlans.id", ondelete="CASCADE"), primary_key=True)
    ip_address = Column(String(64), nullable=True)


device_tagged_vlans = DeviceTaggedVlan.__table__

PORT_MODES = ("access", "trunk")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    ip_address = Column(String(64), nullable=False)
    device_type = Column(Enum(DeviceType), nullable=False, default=DeviceType.other)
    vlan_id = Column(Integer, ForeignKey("vlans.id"), nullable=True)
    # Anschluss am Switch: "access" = genau ein VLAN (vlan_id). "trunk" = mehrere VLANs getaggt
    # (tagged_vlans), vlan_id ist dann das native, ungetaggte VLAN
    port_mode = Column(String(8), default="access", nullable=False, server_default="access")
    is_active = Column(Boolean, default=True, nullable=False)

    # SNMP configuration (optional - only relevant for switch/router)
    snmp_enabled = Column(Boolean, default=False, nullable=False)
    snmp_community = Column(String(128), nullable=True)
    snmp_version = Column(String(8), default="2c", nullable=False)  # "1", "2c", "3"
    snmp_port = Column(Integer, default=161, nullable=False)
    snmp_interfaces = Column(String(255), nullable=True)  # comma-separated ifIndex list, e.g. "1,2,3"
    # SNMP v3 (statt Community): Benutzer, Anmeldung und optional Verschluesselung
    snmp_v3_user = Column(String(32), nullable=True)
    snmp_v3_auth_protocol = Column(String(8), nullable=True)  # md5, sha, sha224 ... sha512
    snmp_v3_auth_password = Column(String(64), nullable=True)
    snmp_v3_priv_protocol = Column(String(8), nullable=True)  # des, aes; leer = nur Anmeldung
    snmp_v3_priv_password = Column(String(64), nullable=True)

    # Custom agent configuration (optional - for NAS/webserver push metrics)
    agent_enabled = Column(Boolean, default=False, nullable=False)
    agent_token = Column(String(128), nullable=True)
    # Letzte Meldung des Agenten - bleibt sie aus, zeigt das Dashboard einen Hinweis
    agent_last_push_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vlan = relationship("Vlan", back_populates="devices")
    # Schreiben ueber tagged_vlan_links, lesen (sortiert nach Tag) ueber tagged_vlans
    tagged_vlan_links = relationship("DeviceTaggedVlan", cascade="all, delete-orphan")
    tagged_vlans = relationship("Vlan", secondary=device_tagged_vlans, order_by="Vlan.tag", viewonly=True)
    thresholds = relationship("ThresholdRule", back_populates="device", cascade="all, delete-orphan")

    @property
    def tagged_vlan_ids(self) -> list[int]:
        return [vlan.id for vlan in self.tagged_vlans]

    @property
    def vlan_addresses(self) -> list[dict]:
        """Adressen in den getaggten VLANs, sortiert nach Tag (nur VLANs mit eingetragener Adresse)."""
        by_vlan = {link.vlan_id: link.ip_address for link in self.tagged_vlan_links if link.ip_address}
        return [{"vlan_id": vlan.id, "ip_address": by_vlan[vlan.id]} for vlan in self.tagged_vlans if vlan.id in by_vlan]


class ThresholdRule(Base):
    """Warning/critical thresholds for one metric on one device."""

    __tablename__ = "threshold_rules"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    metric_name = Column(String(64), nullable=False)

    warning_max = Column(Float, nullable=True)
    critical_max = Column(Float, nullable=True)
    warning_min = Column(Float, nullable=True)
    critical_min = Column(Float, nullable=True)

    # number of consecutive breaching samples required before an alert fires
    consecutive_breaches_required = Column(Integer, default=2, nullable=False)

    device = relationship("Device", back_populates="thresholds")


class MetricSample(Base):
    """A single measured value for a device/metric at a point in time."""

    __tablename__ = "metric_samples"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    metric_name = Column(String(64), nullable=False, index=True)
    value = Column(Float, nullable=False)
    status = Column(Enum(MetricStatus), nullable=False, default=MetricStatus.unknown)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    device = relationship("Device")


class AlertEvent(Base):
    """A state transition (OK->WARNING, WARNING->CRITICAL, ->RECOVERED, ...)."""

    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    metric_name = Column(String(64), nullable=False)
    level = Column(Enum(AlertLevel), nullable=False)
    message = Column(Text, nullable=False)
    value = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    acknowledged_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    notified = Column(Boolean, default=False, nullable=False)

    device = relationship("Device")
    acknowledged_by = relationship("User")
