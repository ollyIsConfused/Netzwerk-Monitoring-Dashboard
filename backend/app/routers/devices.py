from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from shared.models import AlertEvent, Device, MetricSample, MetricStatus, ThresholdRule, User, UserRole, Vlan

from ..deps import get_db
from ..schemas import (
    DeviceConfigOut,
    DeviceCreate,
    DeviceOut,
    DeviceStatusOut,
    DeviceUpdate,
    ThresholdRuleCreate,
    ThresholdRuleOut,
    ThresholdRuleUpdate,
)
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/devices", tags=["devices"])

require_admin = require_roles(UserRole.admin)

# Spalten ohne NULL in der Datenbank: ein explizites null im PATCH wird ignoriert
_NON_NULLABLE_DEVICE_FIELDS = {
    "name", "ip_address", "device_type", "is_active", "snmp_enabled", "snmp_version", "snmp_port", "agent_enabled",
}


def _get_device_or_404(db: Session, device_id: int) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gerät nicht gefunden")
    return device


def _ensure_vlan_exists(db: Session, vlan_id: int | None) -> None:
    if vlan_id is not None and db.query(Vlan).filter(Vlan.id == vlan_id).first() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dieses VLAN existiert nicht")

_STATUS_PRIORITY = {
    MetricStatus.critical: 3,
    MetricStatus.warning: 2,
    MetricStatus.unknown: 1,
    MetricStatus.ok: 0,
}


@router.get("", response_model=list[DeviceOut])
def list_devices(vlan_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    query = db.query(Device)
    if vlan_id is not None:
        query = query.filter(Device.vlan_id == vlan_id)
    return query.order_by(Device.name).all()


@router.get("/status", response_model=list[DeviceStatusOut])
def list_device_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Latest known value per metric, per device, plus an aggregated overall status."""
    devices = db.query(Device).filter(Device.is_active.is_(True)).all()
    results: list[DeviceStatusOut] = []

    for device in devices:
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

        results.append(
            DeviceStatusOut(
                device=DeviceOut.model_validate(device),
                reachable=reachable,
                overall_status=overall,
                latest_metrics={name: s.value for name, s in latest_per_metric.items()},
                last_seen=last_seen,
            )
        )
    return results


@router.post("", response_model=DeviceOut, status_code=201, dependencies=[Depends(require_admin)])
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    _ensure_vlan_exists(db, payload.vlan_id)
    device = Device(**payload.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _get_device_or_404(db, device_id)


@router.get("/{device_id}/config", response_model=DeviceConfigOut, dependencies=[Depends(require_admin)])
def get_device_config(device_id: int, db: Session = Depends(get_db)):
    """Vollstaendige Konfiguration (inkl. SNMP-Community/Agent-Token) fuer das Bearbeiten-Formular."""
    return _get_device_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceOut, dependencies=[Depends(require_admin)])
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    device = _get_device_or_404(db, device_id)
    changes = payload.model_dump(exclude_unset=True)
    if "vlan_id" in changes:
        _ensure_vlan_exists(db, changes["vlan_id"])
    for field, value in changes.items():
        if value is None and field in _NON_NULLABLE_DEVICE_FIELDS:
            continue
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = _get_device_or_404(db, device_id)
    # Messwerte und Alarme verweisen per Fremdschluessel auf das Geraet und muessen
    # zuerst weg, sonst lehnt PostgreSQL das Loeschen ab.
    db.query(MetricSample).filter(MetricSample.device_id == device.id).delete(synchronize_session=False)
    db.query(AlertEvent).filter(AlertEvent.device_id == device.id).delete(synchronize_session=False)
    db.delete(device)
    db.commit()


@router.get("/{device_id}/thresholds", response_model=list[ThresholdRuleOut])
def list_thresholds(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return (
        db.query(ThresholdRule)
        .filter(ThresholdRule.device_id == device_id)
        .order_by(ThresholdRule.metric_name)
        .all()
    )


@router.post(
    "/{device_id}/thresholds",
    response_model=ThresholdRuleOut,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_threshold(device_id: int, payload: ThresholdRuleCreate, db: Session = Depends(get_db)):
    _get_device_or_404(db, device_id)
    existing = (
        db.query(ThresholdRule)
        .filter(ThresholdRule.device_id == device_id, ThresholdRule.metric_name == payload.metric_name)
        .first()
    )
    if existing:
        # Pro Geraet und Metrik darf es nur eine Regel geben, sonst waere die Auswertung mehrdeutig
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Für {payload.metric_name} gibt es schon einen Schwellenwert - bitte bearbeiten",
        )
    rule = ThresholdRule(device_id=device_id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _get_rule_or_404(db: Session, device_id: int, rule_id: int) -> ThresholdRule:
    rule = (
        db.query(ThresholdRule)
        .filter(ThresholdRule.id == rule_id, ThresholdRule.device_id == device_id)
        .first()
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schwellenwert nicht gefunden")
    return rule


@router.patch(
    "/{device_id}/thresholds/{rule_id}",
    response_model=ThresholdRuleOut,
    dependencies=[Depends(require_admin)],
)
def update_threshold(device_id: int, rule_id: int, payload: ThresholdRuleUpdate, db: Session = Depends(get_db)):
    rule = _get_rule_or_404(db, device_id, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "consecutive_breaches_required" and value is None:
            continue
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{device_id}/thresholds/{rule_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_threshold(device_id: int, rule_id: int, db: Session = Depends(get_db)):
    rule = _get_rule_or_404(db, device_id, rule_id)
    db.delete(rule)
    db.commit()
