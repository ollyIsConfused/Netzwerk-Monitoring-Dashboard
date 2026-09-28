import asyncio
import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.database import init_db

from .routers import alerts, auth, devices, metrics, vlans, ws

app = FastAPI(title="Netzwerk-Monitoring-Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # eingeschränkt im Produktivbetrieb über Reverse-Proxy/CORS-Config
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(vlans.router)
app.include_router(devices.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(ws.router)

_broadcast_task: asyncio.Task | None = None


@app.on_event("startup")
def on_startup():
    init_db()
    global _broadcast_task
    _broadcast_task = asyncio.create_task(ws.broadcast_status_loop())


@app.on_event("shutdown")
async def on_shutdown():
    if _broadcast_task is not None:
        _broadcast_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _broadcast_task


@app.get("/health")
def health():
    return {"status": "ok"}
