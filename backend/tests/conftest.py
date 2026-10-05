"""Testumgebung: eigene SQLite-Datenbank pro Testlauf, kein PostgreSQL noetig.

Ausfuehren (aus backend/):
    .venv/bin/pip install -r requirements-dev.txt
    PYTHONPATH=.. .venv/bin/pytest
"""
import os
import tempfile

_db_file = os.path.join(tempfile.mkdtemp(prefix="monitoring-tests-"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["COLLECTOR_API_TOKEN"] = "test-collector-token"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402

from shared.database import Base, SessionLocal, engine  # noqa: E402
from shared.models import User, UserRole  # noqa: E402

from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _record):
    # SQLite prueft Fremdschluessel nur mit diesem Pragma - wie PostgreSQL im Betrieb
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


ADMIN_PASSWORD = "admin-pass-123"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add(User(username="admin", email="admin@example.com", hashed_password=hash_password(ADMIN_PASSWORD),
                role=UserRole.admin))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    # Ohne "with": die Startup-Hintergrundtasks (WebSocket-Broadcast, Mailversand) laufen nicht
    return TestClient(app)


def login(client: TestClient, username: str, password: str) -> dict:
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def activate(client: TestClient, username: str, initial_password: str, new_password: str) -> dict:
    """Erste Anmeldung eines neu angelegten Benutzers inkl. Pflicht-Passwortwechsel."""
    headers = login(client, username, initial_password)
    response = client.post(
        "/auth/change-password",
        json={"current_password": initial_password, "new_password": new_password},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return login(client, "admin", ADMIN_PASSWORD)


class MailBox(list):
    """Abgefangene E-Mails; mail_ok = False simuliert einen fehlgeschlagenen Versand."""

    mail_ok = True


@pytest.fixture
def sent_mails(monkeypatch) -> MailBox:
    from shared import notifier

    mails = MailBox()

    def fake_send_email(recipients, subject, body):
        mails.append({"to": list(recipients), "subject": subject, "body": body})
        return mails.mail_ok

    monkeypatch.setattr(notifier, "send_email", fake_send_email)
    return mails
