"""Aktueller Zustand eines Geraets aus seinen letzten Messwerten.

Gemeinsam fuer GET /devices/status und den WebSocket, damit beide dasselbe anzeigen.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from shared.models import Device, MetricSample, MetricStatus

from . import config

_STATUS_PRIORITY = {
    MetricStatus.critical: 3,
    MetricStatus.warning: 2,
    MetricStatus.unknown: 1,
    MetricStatus.ok: 0,
}


@dataclass
class DeviceState:
    reachable: Optional[bool]
    overall_status: MetricStatus
    latest_metrics: dict[str, float]
    last_seen: Optional[datetime]
    stale: bool
    agent_last_seen: Optional[datetime]
    agent_stale: bool


def is_stale(timestamp: Optional[datetime], now: datetime) -> bool:
    """True, wenn der letzte Messwert aelter als STALE_AFTER_SECONDS ist (z. B. Collector gestoppt)."""
    if timestamp is None:
        return False
    if timestamp.tzinfo is not None:
        # Gespeichert wird UTC ohne Zeitzone
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    return now - timestamp > timedelta(seconds=config.STALE_AFTER_SECONDS)


def device_state(db: Session, device: Device, now: Optional[datetime] = None) -> DeviceState:
    now = now or datetime.utcnow()
    latest_per_metric: dict[str, MetricSample] = {}
    samples = (
        db.query(MetricSample)
        .filter(MetricSample.device_id == device.id)
        .order_by(MetricSample.timestamp.desc())
        .limit(200)
        .all()
    )
    for sample in samples:
        if sample.metric_name not in latest_per_metric:
            latest_per_metric[sample.metric_name] = sample

    overall = MetricStatus.unknown
    if latest_per_metric:
        overall = max((s.status for s in latest_per_metric.values()), key=lambda st: _STATUS_PRIORITY[st])

    reachable = None
    last_seen = None
    if "reachable" in latest_per_metric:
        reachable = latest_per_metric["reachable"].value >= 1
        last_seen = latest_per_metric["reachable"].timestamp

    # Der Collector pingt jedes aktive Geraet in jeder Runde - bleibt das aus, ist der
    # angezeigte Status nicht mehr aktuell
    stale = is_stale(last_seen, now)
    if stale:
        overall = MetricStatus.unknown

    agent_last_seen = device.agent_last_push_at if device.agent_enabled else None
    return DeviceState(
        reachable=reachable,
        overall_status=overall,
        latest_metrics={name: s.value for name, s in latest_per_metric.items()},
        last_seen=last_seen,
        stale=stale,
        agent_last_seen=agent_last_seen,
        agent_stale=is_stale(agent_last_seen, now),
    )
