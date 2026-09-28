"""Shared logic for storing a metric sample, evaluating thresholds and raising alerts.

Used by the collector (SNMP/ping polling) and by the backend's agent-push endpoint,
so both paths behave identically and alerts are never duplicated.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .models import AlertEvent, AlertLevel, Device, MetricSample, MetricStatus, ThresholdRule


def _evaluate_status(value: float, rule: Optional[ThresholdRule]) -> MetricStatus:
    if rule is None:
        return MetricStatus.ok
    if rule.critical_max is not None and value >= rule.critical_max:
        return MetricStatus.critical
    if rule.critical_min is not None and value <= rule.critical_min:
        return MetricStatus.critical
    if rule.warning_max is not None and value >= rule.warning_max:
        return MetricStatus.warning
    if rule.warning_min is not None and value <= rule.warning_min:
        return MetricStatus.warning
    return MetricStatus.ok


def _recent_statuses(db: Session, device_id: int, metric_name: str, limit: int) -> list[MetricStatus]:
    rows = (
        db.query(MetricSample.status)
        .filter(MetricSample.device_id == device_id, MetricSample.metric_name == metric_name)
        .order_by(MetricSample.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def _last_alert_level(db: Session, device_id: int, metric_name: str) -> Optional[AlertLevel]:
    last = (
        db.query(AlertEvent)
        .filter(AlertEvent.device_id == device_id, AlertEvent.metric_name == metric_name)
        .order_by(AlertEvent.created_at.desc())
        .first()
    )
    return last.level if last else None


def record_metric(
    db: Session,
    device: Device,
    metric_name: str,
    value: float,
    timestamp: Optional[datetime] = None,
) -> MetricSample:
    """Store one metric sample, evaluate its threshold and raise/resolve alerts as needed.

    Commits the session. Returns the stored MetricSample.
    """
    rule = next((t for t in device.thresholds if t.metric_name == metric_name), None)
    status = _evaluate_status(value, rule)

    sample = MetricSample(
        device_id=device.id,
        metric_name=metric_name,
        value=value,
        status=status,
        timestamp=timestamp or datetime.utcnow(),
    )
    db.add(sample)
    db.flush()

    required = rule.consecutive_breaches_required if rule else 1
    target_level = None
    if status == MetricStatus.critical:
        target_level = AlertLevel.critical
    elif status == MetricStatus.warning:
        target_level = AlertLevel.warning

    last_level = _last_alert_level(db, device.id, metric_name)

    if target_level is not None:
        recent = _recent_statuses(db, device.id, metric_name, required)
        breach_matches = all(s == status for s in recent) and len(recent) >= required
        if breach_matches and last_level != target_level:
            event = AlertEvent(
                device_id=device.id,
                metric_name=metric_name,
                level=target_level,
                message=(
                    f"{device.name}: {metric_name} = {value} "
                    f"({'kritisch' if target_level == AlertLevel.critical else 'Warnung'})"
                ),
                value=value,
            )
            db.add(event)
    elif last_level in (AlertLevel.warning, AlertLevel.critical):
        event = AlertEvent(
            device_id=device.id,
            metric_name=metric_name,
            level=AlertLevel.recovered,
            message=f"{device.name}: {metric_name} wieder im Normalbereich ({value})",
            value=value,
        )
        db.add(event)

    db.commit()
    db.refresh(sample)
    return sample
