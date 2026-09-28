from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.models import AlertEvent, User, UserRole

from ..deps import get_db
from ..schemas import AlertEventOut
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertEventOut])
def list_alerts(
    active_only: bool = False,
    device_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(AlertEvent)
    if device_id is not None:
        query = query.filter(AlertEvent.device_id == device_id)
    if active_only:
        query = query.filter(AlertEvent.resolved_at.is_(None), AlertEvent.acknowledged_at.is_(None))
    return query.order_by(AlertEvent.created_at.desc()).limit(limit).all()


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertEventOut,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.operator))],
)
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    alert = db.query(AlertEvent).filter(AlertEvent.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alarm nicht gefunden")
    alert.acknowledged_by_id = user.id
    alert.acknowledged_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    return alert
