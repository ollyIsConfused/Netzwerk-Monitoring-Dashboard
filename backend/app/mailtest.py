"""Schickt eine Test-Mail, um die SMTP-Einstellungen aus der .env zu pruefen.

Aufruf (aus backend/, mit geladener .env):
    python -m app.mailtest                # an die Empfaenger von "Passwort vergessen"-Anfragen
    python -m app.mailtest <adresse>
"""
import logging
import sys

from shared import notifier
from shared.database import SessionLocal

from .account_mails import admin_recipients


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if not notifier.SMTP_HOST:
        print("SMTP_HOST ist in der .env nicht gesetzt - es werden keine E-Mails verschickt.")
        return 1

    if len(sys.argv) > 1:
        recipients = sys.argv[1:]
    else:
        db = SessionLocal()
        try:
            recipients = admin_recipients(db)
        finally:
            db.close()
    if not recipients:
        print("Kein Empfänger: Adresse angeben, ADMIN_NOTIFY_EMAIL setzen oder einen aktiven Admin anlegen.")
        return 1

    print(f"Sende Test-Mail über {notifier.SMTP_HOST}:{notifier.SMTP_PORT} an {', '.join(recipients)} ...")
    ok = notifier.send_email(
        recipients,
        "[Netzwerk-Monitoring] Test-Mail",
        "Die SMTP-Einstellungen funktionieren: Alarm-Mails und Passwort-Mails können verschickt werden.\n",
    )
    if ok:
        print("Gesendet. Falls nichts ankommt: Spam-Ordner prüfen.")
        return 0
    print("Versand fehlgeschlagen - die Ursache steht in der Meldung oben.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
