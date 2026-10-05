import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.database import init_db

from .notifications import dispatch_alert_emails_loop
from .routers import alerts, auth, collector, devices, metrics, users, vlans, ws

app = FastAPI(title="Netzwerk-Monitoring-Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # eingeschränkt im Produktivbetrieb über Reverse-Proxy/CORS-Config
    allow_credentials=True,
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
