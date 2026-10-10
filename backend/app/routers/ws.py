import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.database import SessionLocal
from shared.models import Device

from ..config import STATUS_BROADCAST_INTERVAL_SECONDS
from ..device_status import device_state
from ..security import user_from_token

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

# So lange wartet der Server nach dem Verbindungsaufbau auf die Anmeldung
AUTH_TIMEOUT_SECONDS = 10
# Eigener Close-Code (4000-4999 sind fuer Anwendungen frei): Anmeldung fehlt oder ist ungueltig
CLOSE_UNAUTHORIZED = 4401

# Verbindung -> Token, mit dem sie sich angemeldet hat (wird vor jedem Senden erneut geprueft)
_active_connections: dict[WebSocket, str] = {}


def _current_status_snapshot() -> list[dict]:
    db = SessionLocal()
    try:
        devices = db.query(Device).filter(Device.is_active.is_(True)).all()
        now = datetime.utcnow()
        # Derselbe Gesamtstatus wie GET /devices/status (inkl. "veraltet" -> unknown)
        return [
            {"device_id": device.id, "name": device.name, "status": device_state(db, device, now).overall_status.value}
            for device in devices
        ]
    finally:
        db.close()


def _valid_tokens(tokens: set[str]) -> set[str]:
    """Die Tokens, die noch gelten: nicht abgelaufen, Konto aktiv, Passwort nicht geaendert,
    kein Pflicht-Passwortwechsel offen."""
    db = SessionLocal()
    try:
        valid = set()
        for token in tokens:
            user = user_from_token(db, token)
            if user is not None and not user.must_change_password:
                valid.add(token)
        return valid
    finally:
        db.close()


async def _run_in_thread(func, *args):
    return await asyncio.get_event_loop().run_in_executor(None, func, *args)


@router.websocket("/ws/status")
async def status_websocket(websocket: WebSocket):
    # Browser koennen beim WebSocket keinen Authorization-Header setzen. Das Token kommt
    # deshalb als erste Nachricht {"type": "auth", "token": "..."} - nicht in der URL, wo es
    # in den Zugriffslogs von nginx und Caddy landen wuerde.
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        message = json.loads(raw)
        token = message.get("token") if isinstance(message, dict) and message.get("type") == "auth" else None
    except (asyncio.TimeoutError, ValueError, KeyError):  # KeyError: Binaer- statt Textnachricht
        token = None
    except WebSocketDisconnect:
        return

    if not isinstance(token, str) or not token or token not in await _run_in_thread(_valid_tokens, {token}):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    # Gleich den aktuellen Stand schicken, nicht erst beim naechsten Durchlauf
    await websocket.send_text(json.dumps({"type": "status", "devices": await _run_in_thread(_current_status_snapshot)}))
    _active_connections[websocket] = token
    try:
        while True:
            await websocket.receive_text()  # keep the connection alive; client pings are ignored
    except WebSocketDisconnect:
        pass
    finally:
        _active_connections.pop(websocket, None)


async def broadcast_status_loop():
    """Background task started at app startup: periodically pushes the latest
    device status to every connected websocket client."""
    while True:
        await asyncio.sleep(STATUS_BROADCAST_INTERVAL_SECONDS)
        if not _active_connections:
            continue
        try:
            valid = await _run_in_thread(_valid_tokens, set(_active_connections.values()))
            snapshot = await _run_in_thread(_current_status_snapshot)
        except Exception:
            logger.exception("Failed to build status snapshot for websocket broadcast")
            continue
        message = json.dumps({"type": "status", "devices": snapshot})
        for connection, token in list(_active_connections.items()):
            try:
                if token in valid:
                    await connection.send_text(message)
                else:
                    # Abgelaufen, abgemeldet oder Passwort geaendert: Verbindung beenden
                    await connection.close(code=CLOSE_UNAUTHORIZED)
                    _active_connections.pop(connection, None)
            except Exception:
                _active_connections.pop(connection, None)
