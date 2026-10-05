"""Sends e-mails via SMTP: alert notifications and account mails (password reset).

Lives in shared/ (not backend/ or collector/) because it has no database or
web-framework dependency of its own - just stdlib smtplib - and is invoked by
the backend's alert-dispatch background task.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
# Gmail & Co. akzeptieren als Absender nur das eigene Konto - daher standardmaessig SMTP_USER
ALERT_EMAIL_FROM = os.environ.get("ALERT_EMAIL_FROM") or SMTP_USER or "monitoring@localhost"
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")


def split_addresses(value: str) -> list[str]:
    return [addr.strip() for addr in value.split(",") if addr.strip()]


def send_email(recipients: Iterable[str], subject: str, body: str) -> bool:
    """Schickt eine Text-Mail. Gibt False zurueck statt zu werfen, wenn SMTP nicht
    eingerichtet ist oder der Versand scheitert - die Ursache steht im Log (ohne Mailtext)."""
    recipients = [addr for addr in recipients if addr]
    if not SMTP_HOST or not recipients:
        logger.warning("SMTP nicht konfiguriert oder kein Empfänger - E-Mail nicht gesendet: %s", subject)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = ALERT_EMAIL_FROM
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    # Zertifikat des Mailservers pruefen, damit die SMTP-Zugangsdaten nicht abgefangen werden koennen
    tls = ssl.create_default_context()
    try:
        if SMTP_PORT == 465:
            # Port 465: TLS von Anfang an (SMTPS); sonst unverschluesselt verbinden und STARTTLS
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10, context=tls)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        with server:
            if SMTP_PORT != 465:
                server.starttls(context=tls)
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message, from_addr=ALERT_EMAIL_FROM, to_addrs=recipients)
        return True
    except Exception:
        logger.exception("E-Mail-Versand fehlgeschlagen: %s", subject)
        return False


def send_alert_email(subject: str, body: str) -> None:
    if not SMTP_HOST or not ALERT_EMAIL_TO:
        logger.warning("SMTP nicht konfiguriert - Alarm wird nur geloggt: %s | %s", subject, body)
        return
    send_email(split_addresses(ALERT_EMAIL_TO), subject, body)
