from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.models import Device, MetricSample, MetricStatus, User, UserRole

from ..deps import get_db
from ..schemas import DeviceCreate, DeviceOut, DeviceStatusOut, DeviceUpdate, ThresholdRuleCreate, ThresholdRuleOut
from ..security import get_current_user, require_roles
from shared.models import ThresholdRule

router = APIRouter(prefix="/devices", tags=["devices"])

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


@router.post("", response_model=DeviceOut, dependencies=[Depends(require_roles(UserRole.admin))])
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    device = Device(**payload.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.patch("/{device_id}", response_model=DeviceOut, dependencies=[Depends(require_roles(UserRole.admin))])
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204, dependencies=[Depends(require_roles(UserRole.admin))])
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    db.delete(device)
    db.commit()


@router.get("/{device_id}/thresholds", response_model=list[ThresholdRuleOut])
def list_thresholds(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(ThresholdRule).filter(ThresholdRule.device_id == device_id).all()


@router.post(
    "/{device_id}/thresholds",
    response_model=ThresholdRuleOut,
    dependencies=[Depends(require_roles(UserRole.admin))],
)
def create_threshold(device_id: int, payload: ThresholdRuleCreate, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    rule = ThresholdRule(device_id=device_id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
