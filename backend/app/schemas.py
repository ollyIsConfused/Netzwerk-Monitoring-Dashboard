from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from shared.models import AlertLevel, DeviceType, MetricStatus, UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool


class VlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    tag: int
    description: Optional[str] = None


class VlanCreate(BaseModel):
    name: str
    tag: int
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
    metric_name: str
    warning_max: Optional[float] = None
    critical_max: Optional[float] = None
    warning_min: Optional[float] = None
    critical_min: Optional[float] = None
    consecutive_breaches_required: int = 2


class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    device_type: DeviceType
    vlan_id: Optional[int] = None
    is_active: bool = True
    snmp_enabled: bool = False
    snmp_community: Optional[str] = None
    snmp_version: str = "2c"
    snmp_port: int = 161
    snmp_interfaces: Optional[str] = None
    agent_enabled: bool = False
    agent_token: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    device_type: Optional[DeviceType] = None
    vlan_id: Optional[int] = None
    is_active: Optional[bool] = None
    snmp_enabled: Optional[bool] = None
    snmp_community: Optional[str] = None
    snmp_version: Optional[str] = None
    snmp_port: Optional[int] = None
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
