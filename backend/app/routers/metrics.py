from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.metrics_engine import record_metric
from shared.models import Device, MetricSample, User

from ..deps import get_db
from ..schemas import AgentMetricPush, MetricSampleOut
from ..security import get_current_user

router = APIRouter(tags=["metrics"])


@router.get("/devices/{device_id}/metrics", response_model=list[MetricSampleOut])
def get_device_metrics(
    device_id: int,
    metric_name: str | None = None,
    since_minutes: int = 60,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    since = datetime.utcnow() - timedelta(minutes=since_minutes)
    query = db.query(MetricSample).filter(
        MetricSample.device_id == device_id, MetricSample.timestamp >= since
    )
    if metric_name:
        query = query.filter(MetricSample.metric_name == metric_name)
    return query.order_by(MetricSample.timestamp.asc()).all()


@router.post("/agent/push", status_code=202)
def push_agent_metrics(payload: AgentMetricPush, db: Session = Depends(get_db)):
    """Endpoint for custom agents (e.g. on the NAS/webserver) to push metrics.

    Authenticated via a per-device agent token instead of a user JWT, since the
    agent runs unattended on the monitored host.
    """
    device = (
        db.query(Device)
        .filter(Device.agent_enabled.is_(True), Device.agent_token == payload.agent_token)
        .first()
    )
    if device is None:
        raise HTTPException(status_code=401, detail="Unbekanntes oder ungültiges Agent-Token")

    for metric_name, value in payload.metrics.items():
        record_metric(db, device, metric_name, value)

    return {"stored": len(payload.metrics)}
