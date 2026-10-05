import ipaddress
import re
from datetime import datetime
from typing import Annotated, Optional

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


def _validate_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_RE.match(value):
        raise ValueError("Keine gültige E-Mail-Adresse")
    return value


HostStr = Annotated[str, AfterValidator(_validate_host)]
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


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    ip_address: HostStr
    device_type: DeviceType
    vlan_id: Optional[int] = None
    is_active: bool = True
    snmp_enabled: bool = False
    snmp_community: Optional[str] = None
    snmp_version: str = "2c"
    snmp_port: int = Field(default=161, ge=1, le=65535)
    snmp_interfaces: Optional[str] = None
    agent_enabled: bool = False
    agent_token: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    ip_address: Optional[HostStr] = None
    device_type: Optional[DeviceType] = None
    vlan_id: Optional[int] = None
    is_active: Optional[bool] = None
    snmp_enabled: Optional[bool] = None
    snmp_community: Optional[str] = None
    snmp_version: Optional[str] = None
    snmp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    snmp_interfaces: Optional[str] = None
    agent_enabled: Optional[bool] = None
    agent_token: Optional[str] = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ip_address: str
    device_type: DeviceType
    vlan_id: Optional[int] = None
    is_active: bool
    snmp_enabled: bool
    agent_enabled: bool


class DeviceConfigOut(DeviceOut):
    """Vollstaendige Geraetekonfiguration inkl. SNMP-Community/Agent-Token - nur fuer Admins."""

    snmp_community: Optional[str] = None
    snmp_version: str
    snmp_port: int
    snmp_interfaces: Optional[str] = None
    agent_token: Optional[str] = None


class DeviceStatusOut(BaseModel):
    device: DeviceOut
    reachable: Optional[bool] = None
    overall_status: MetricStatus
    latest_metrics: dict[str, float]
    last_seen: Optional[datetime] = None


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
    metrics: dict[str, float]


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


class CollectorMetricIn(BaseModel):
    device_id: int
    metric_name: str
    value: float
    timestamp: Optional[datetime] = None


class CollectorMetricBatch(BaseModel):
    samples: list[CollectorMetricIn]
