"""Sends e-mail notifications for alert events via SMTP.

Lives in shared/ (not backend/ or collector/) because it has no database or
web-framework dependency of its own - just stdlib smtplib - and is invoked by
the backend's alert-dispatch background task.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
ALERT_EMAIL_FROM = os.environ.get("ALERT_EMAIL_FROM", "monitoring@example.com")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")


def send_alert_email(subject: str, body: str) -> None:
    if not SMTP_HOST or not ALERT_EMAIL_TO:
        logger.warning("SMTP nicht konfiguriert - Alarm wird nur geloggt: %s | %s", subject, body)
        return

    recipients = [addr.strip() for addr in ALERT_EMAIL_TO.split(",") if addr.strip()]
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = ALERT_EMAIL_FROM
    message["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(ALERT_EMAIL_FROM, recipients, message.as_string())
    except Exception:
        logger.exception("Versand der Alarm-E-Mail fehlgeschlagen")
