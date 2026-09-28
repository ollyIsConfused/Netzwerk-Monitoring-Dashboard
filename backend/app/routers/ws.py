import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.database import SessionLocal
from shared.models import Device, MetricSample, MetricStatus

from ..config import STATUS_BROADCAST_INTERVAL_SECONDS

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

_active_connections: set[WebSocket] = set()


def _current_status_snapshot() -> list[dict]:
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(Device.is_active.is_(True)).all()
        snapshot = []
        for device in devices:
            latest = (
                db.query(MetricSample)
                .filter(MetricSample.device_id == device.id)
                .order_by(MetricSample.timestamp.desc())
                .first()
            )
            status = latest.status.value if latest else MetricStatus.unknown.value
            snapshot.append({"device_id": device.id, "name": device.name, "status": status})
        return snapshot
    finally:
        db.close()


@router.websocket("/ws/status")
async def status_websocket(websocket: WebSocket):
    await websocket.accept()
    _active_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the connection alive; client pings are ignored
    except WebSocketDisconnect:
        pass
    finally:
        _active_connections.discard(websocket)


async def broadcast_status_loop():
    """Background task started at app startup: periodically pushes the latest
    device status to every connected websocket client."""
    while True:
        await asyncio.sleep(STATUS_BROADCAST_INTERVAL_SECONDS)
        if not _active_connections:
            continue
        try:
            snapshot = await asyncio.get_event_loop().run_in_executor(None, _current_status_snapshot)
        except Exception:
            logger.exception("Failed to build status snapshot for websocket broadcast")
            continue
        message = json.dumps({"type": "status", "devices": snapshot})
        stale = []
        for connection in list(_active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            _active_connections.discard(connection)
