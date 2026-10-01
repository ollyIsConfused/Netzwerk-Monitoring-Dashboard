import asyncio
import logging

from shared.database import SessionLocal
from shared.models import AlertEvent, AlertLevel
from shared.notifier import send_alert_email

from .config import ALERT_DISPATCH_INTERVAL_SECONDS

logger = logging.getLogger(__name__)

_LEVEL_LABELS = {
    AlertLevel.warning: "WARNUNG",
    AlertLevel.critical: "KRITISCH",
    AlertLevel.recovered: "WIEDERHERGESTELLT",
}


def _dispatch_pending_notifications() -> None:
    db = SessionLocal()
    try:
        pending = db.query(AlertEvent).filter(AlertEvent.notified.is_(False)).order_by(AlertEvent.created_at).all()
        for event in pending:
            send_alert_email(
                subject=f"[{_LEVEL_LABELS[event.level]}] Netzwerk-Monitoring: {event.message}",
                body=f"{event.message}\nZeitpunkt: {event.created_at.isoformat()}",
            )
            event.notified = True
        if pending:
            db.commit()
    finally:
        db.close()


async def dispatch_alert_emails_loop():
    """Background task started at app startup: periodically sends e-mails for
    alert events raised by either the collector (/collector/metrics) or a
    custom agent (/agent/push) that haven't been notified yet."""
    while True:
        await asyncio.sleep(ALERT_DISPATCH_INTERVAL_SECONDS)
        try:
            await asyncio.get_event_loop().run_in_executor(None, _dispatch_pending_notifications)
        except Exception:
            logger.exception("Alarm-E-Mail-Versand fehlgeschlagen")
