from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.metrics_engine import record_metric
from shared.models import Device

from ..deps import get_db
from ..schemas import CollectorDeviceOut, CollectorMetricBatch
from ..security import require_collector_token

router = APIRouter(prefix="/collector", tags=["collector"], dependencies=[Depends(require_collector_token)])


@router.get("/devices", response_model=list[CollectorDeviceOut])
def list_devices_for_collector(db: Session = Depends(get_db)):
    """Polling config for every active device - consumed by the standalone collector
    service, which otherwise has no database access (see shared/metrics_engine.py)."""
    return db.query(Device).filter(Device.is_active.is_(True)).all()


@router.post("/metrics", status_code=202)
def push_collector_metrics(payload: CollectorMetricBatch, db: Session = Depends(get_db)):
    devices_by_id: dict[int, Device] = {}
    stored = 0

    for sample in payload.samples:
        device = devices_by_id.get(sample.device_id)
        if device is None:
            device = db.query(Device).filter(Device.id == sample.device_id).first()
            if device is None:
                raise HTTPException(status_code=404, detail=f"Gerät {sample.device_id} nicht gefunden")
            devices_by_id[sample.device_id] = device

        record_metric(db, device, sample.metric_name, sample.value, sample.timestamp)
        stored += 1

    return {"stored": stored}
