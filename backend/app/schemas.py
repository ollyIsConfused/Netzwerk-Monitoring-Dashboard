import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from shared.models import AlertLevel, DeviceType, MetricStatus, UserRole

# bcrypt verarbeitet maximal 72 Byte, laengere Passwoerter wuerden still abgeschnitten
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,62})(\.[A-Za-z0-9]([A-Za-z0-9-]{0,62}))*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_host(value: str) -> str:
    value = value.strip()
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(value):
        raise ValueError("Keine gültige IP-Adresse oder kein gültiger Hostname")
    return value


def _validate_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        raise ValueError("Keine gültige IP-Adresse") from None


def _validate_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError("Keine gültige E-Mail-Adresse")
    return value


HostStr = Annotated[str, AfterValidator(_validate_host)]
IpStr = Annotated[str, AfterValidator(_validate_ip)]
PortMode = Literal["access", "trunk"]
SnmpVersion = Literal["1", "2c", "3"]
SnmpAuthProtocol = Literal["md5", "sha", "sha224", "sha256", "sha384", "sha512"]
SnmpPrivProtocol = Literal["des", "aes"]
EmailStr = Annotated[str, AfterValidator(_validate_email)]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str
    must_change_password: bool = False


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    must_change_password: bool
    password_reset_requested_at: Optional[datetime]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    # Ohne Passwort: der Admin schickt danach ein Einmal-Passwort per E-Mail
    password: Optional[str] = Field(default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    role: UserRole = UserRole.viewer


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    # Admin setzt ein neues Passwort, z. B. wenn ein Benutzer seins vergessen hat
    password: Optional[str] = Field(default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    # Lockfeld (Honeypot): im Formular unsichtbar, muss leer bleiben
    phone: str = Field(default="", max_length=200)


class TemporaryPasswordResult(BaseModel):
    email: str
    email_sent: bool
    # Nur wenn die E-Mail nicht rausging - dann gibt der Admin das Passwort selbst weiter
    temporary_password: Optional[str] = None


class VlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    tag: int
    description: Optional[str] = None


class VlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tag: int = Field(ge=1, le=4094)
    description: Optional[str] = None


class VlanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    tag: Optional[int] = Field(default=None, ge=1, le=4094)
    description: Optional[str] = None


class ThresholdRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_name: str
    warning_max: Optional[float] = None
    critical_max: Optional[float] = None
    warning_min: Optional[float] = None
    critical_min: Optional[float] = None
    consecutive_breaches_required: int


class ThresholdRuleCreate(BaseModel):
    metric_name: str = Field(min_length=1, max_length=64)
    warning_max: Optional[float] = None
    critical_max: Optional[float] = None
    warning_min: Optional[float] = None
    critical_min: Optional[float] = None
    consecutive_breaches_required: int = Field(default=2, ge=1, le=100)


class ThresholdRuleUpdate(BaseModel):
    warning_max: Optional[float] = None
    critical_max: Optional[float] = None
    warning_min: Optional[float] = None
    critical_min: Optional[float] = None
    consecutive_breaches_required: Optional[int] = Field(default=None, ge=1, le=100)


class VlanAddress(BaseModel):
    """Adresse eines Trunk-Geraets in einem seiner getaggten VLANs (beim Router: das Gateway)."""

    model_config = ConfigDict(from_attributes=True)
    vlan_id: int
    ip_address: IpStr


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip_address: HostStr
    device_type: DeviceType
    # access: vlan_id ist das VLAN des Geraets. trunk: vlan_id ist das native (ungetaggte) VLAN,
    # tagged_vlan_ids die getaggten VLANs
    port_mode: PortMode = "access"
    vlan_id: Optional[int] = None
    tagged_vlan_ids: list[int] = Field(default_factory=list)
    # Optional je getaggtem VLAN; ueberwacht wird weiter ip_address
    vlan_addresses: list[VlanAddress] = Field(default_factory=list)
    is_active: bool = True
    snmp_enabled: bool = False
    snmp_community: Optional[str] = None
    snmp_version: SnmpVersion = "2c"
    snmp_port: int = Field(default=161, ge=1, le=65535)
    snmp_interfaces: Optional[str] = None
    # Nur bei snmp_version "3"; ohne priv_protocol nur Anmeldung, keine Verschluesselung
    snmp_v3_user: Optional[str] = Field(default=None, max_length=32)
    snmp_v3_auth_protocol: Optional[SnmpAuthProtocol] = None
    snmp_v3_auth_password: Optional[str] = Field(default=None, max_length=64)
    snmp_v3_priv_protocol: Optional[SnmpPrivProtocol] = None
    snmp_v3_priv_password: Optional[str] = Field(default=None, max_length=64)
    agent_enabled: bool = False
    agent_token: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    ip_address: Optional[HostStr] = None
    device_type: Optional[DeviceType] = None
    port_mode: Optional[PortMode] = None
    vlan_id: Optional[int] = None
    tagged_vlan_ids: Optional[list[int]] = None
    vlan_addresses: Optional[list[VlanAddress]] = None
    is_active: Optional[bool] = None
    snmp_enabled: Optional[bool] = None
    snmp_community: Optional[str] = None
    snmp_version: Optional[SnmpVersion] = None
    snmp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    snmp_interfaces: Optional[str] = None
    snmp_v3_user: Optional[str] = Field(default=None, max_length=32)
    snmp_v3_auth_protocol: Optional[SnmpAuthProtocol] = None
    snmp_v3_auth_password: Optional[str] = Field(default=None, max_length=64)
    snmp_v3_priv_protocol: Optional[SnmpPrivProtocol] = None
    snmp_v3_priv_password: Optional[str] = Field(default=None, max_length=64)
    agent_enabled: Optional[bool] = None
    agent_token: Optional[str] = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ip_address: str
    device_type: DeviceType
    port_mode: PortMode
    vlan_id: Optional[int] = None
    tagged_vlan_ids: list[int] = []
    vlan_addresses: list[VlanAddress] = []
    is_active: bool
    snmp_enabled: bool
    snmp_version: str = "2c"
    agent_enabled: bool


class DeviceConfigOut(DeviceOut):
    """Vollstaendige Geraetekonfiguration inkl. SNMP-Zugangsdaten/Agent-Token - nur fuer Admins."""

    snmp_community: Optional[str] = None
    snmp_version: str
    snmp_port: int
    snmp_interfaces: Optional[str] = None
    snmp_v3_user: Optional[str] = None
    snmp_v3_auth_protocol: Optional[str] = None
    snmp_v3_auth_password: Optional[str] = None
    snmp_v3_priv_protocol: Optional[str] = None
    snmp_v3_priv_password: Optional[str] = None
    agent_token: Optional[str] = None


class DeviceStatusOut(BaseModel):
    device: DeviceOut
    # Letzter bekannter Wert - bei stale=True nicht mehr aktuell
    reachable: Optional[bool] = None
    overall_status: MetricStatus
    latest_metrics: dict[str, float]
    last_seen: Optional[datetime] = None
    # Seit STALE_AFTER_SECONDS kein neuer Messwert vom Collector
    stale: bool = False
    agent_last_seen: Optional[datetime] = None
    agent_stale: bool = False


class MetricSampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    metric_name: str
    value: float
    status: MetricStatus
    timestamp: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    metric_name: str
    level: AlertLevel
    message: str
    value: Optional[float] = None
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class AgentMetricPush(BaseModel):
    """Payload a custom agent (e.g. on the NAS/webserver) pushes to the backend."""

    agent_token: str
    metrics: dict[Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")], float]


class CollectorDeviceOut(BaseModel):
    """Device polling config as handed to the collector service (no user-facing fields)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ip_address: str
    device_type: DeviceType
    snmp_enabled: bool
    snmp_community: Optional[str] = None
    snmp_version: str
    snmp_port: int
    snmp_interfaces: Optional[str] = None
    snmp_v3_user: Optional[str] = None
    snmp_v3_auth_protocol: Optional[str] = None
    snmp_v3_auth_password: Optional[str] = None
    snmp_v3_priv_protocol: Optional[str] = None
    snmp_v3_priv_password: Optional[str] = None


class CollectorMetricIn(BaseModel):
    device_id: int
    metric_name: str
    value: float
    timestamp: Optional[datetime] = None


class CollectorMetricBatch(BaseModel):
    samples: list[CollectorMetricIn]
