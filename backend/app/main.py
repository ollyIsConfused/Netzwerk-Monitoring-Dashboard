import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.database import init_db

from .config import CORS_ORIGINS, ENABLE_API_DOCS
from .notifications import dispatch_alert_emails_loop
from .routers import alerts, auth, collector, devices, metrics, users, vlans, ws

# Die API-Beschreibung verraet alle Endpunkte - im Betrieb nur mit ENABLE_API_DOCS=1
app = FastAPI(
    title="Netzwerk-Monitoring-Dashboard API",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)

if CORS_ORIGINS:
    # Die Anmeldung laeuft ueber den Authorization-Header, Cookies braucht es nicht
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(vlans.router)
app.include_router(devices.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(collector.router)
app.include_router(ws.router)

_background_tasks: list[asyncio.Task] = []


@app.on_event("startup")
def on_startup():
    init_db()
    _background_tasks.append(asyncio.create_task(ws.broadcast_status_loop()))
    _background_tasks.append(asyncio.create_task(dispatch_alert_emails_loop()))


@app.on_event("shutdown")
async def on_shutdown():
    for task in _background_tasks:
        task.cancel()
    for task in _background_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _background_tasks.clear()


@app.get("/health")
def health():
    return {"status": "ok"}
