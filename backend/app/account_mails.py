"""E-Mails rund ums Benutzerkonto: "Passwort vergessen"-Anfrage an die Admins und
Einmal-Passwort an den Benutzer. Versand ueber shared/notifier.py (SMTP aus der .env)."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared import notifier
from shared.models import User, UserRole

from .config import ADMIN_NOTIFY_EMAIL, DASHBOARD_URL


def admin_recipients(db: Session) -> list[str]:
    """ADMIN_NOTIFY_EMAIL aus der .env, sonst die Adressen aller aktiven Admins."""
    configured = notifier.split_addresses(ADMIN_NOTIFY_EMAIL)
    if configured:
        return configured
    admins = db.query(User).filter(User.role == UserRole.admin, User.is_active.is_(True)).all()
    return [admin.email for admin in admins]


def _local_time(value: datetime) -> str:
    # In der Datenbank steht UTC; in der Mail die Ortszeit des Servers
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M Uhr")


def notify_password_reset_request(recipients: list[str], username: str, email: str, requested_at: datetime) -> bool:
    link = f"\n{DASHBOARD_URL}/admin/users\n" if DASHBOARD_URL else ""
    body = f"""Im Netzwerk-Monitoring-Dashboard wurde ein neues Passwort angefordert.

Benutzername: {username}
E-Mail:       {email}
Zeitpunkt:    {_local_time(requested_at)}

So geht es weiter: Dashboard > Verwaltung > Benutzer > bei "{username}" auf das
Schlüssel-Symbol ("Einmal-Passwort senden"). Das Dashboard schickt dann ein
Einmal-Passwort an {email}. Nach dem Anmelden damit muss sofort ein eigenes
Passwort festgelegt werden.
{link}
Kam die Anfrage nicht vom Benutzer selbst, diese Mail einfach ignorieren -
am Konto ändert sich dadurch nichts.
"""
    return notifier.send_email(recipients, f"[Netzwerk-Monitoring] Passwort vergessen: {username}", body)


def send_temporary_password(user: User, password: str) -> bool:
    login = f"Anmelden:        {DASHBOARD_URL}/login\n" if DASHBOARD_URL else ""
    body = f"""Hallo {user.username},

für dein Konto im Netzwerk-Monitoring-Dashboard wurde ein Einmal-Passwort erstellt.

Benutzername:    {user.username}
Einmal-Passwort: {password}
{login}
Nach dem Anmelden musst du sofort ein eigenes Passwort festlegen. Das
Einmal-Passwort gilt danach nicht mehr.

Hast du kein neues Passwort angefordert, melde dich bitte beim Administrator.
"""
    return notifier.send_email([user.email], "[Netzwerk-Monitoring] Dein Einmal-Passwort", body)
