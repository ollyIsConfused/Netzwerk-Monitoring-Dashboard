import re

from sqlalchemy import create_engine, inspect, text

from shared.database import Base, SessionLocal, add_missing_columns
from shared.models import User

from app import account_mails, seed
from app.security import PASSWORD_CHANGE_REQUIRED

from .conftest import activate, login

TEMPORARY_PASSWORD_RE = re.compile(r"Einmal-Passwort: (\S+)")


def _create_user(client, admin_headers, username="anna", password="anna-start-1", role="viewer"):
    payload = {"username": username, "email": f"{username}@example.com", "role": role}
    if password:
        payload["password"] = password
    response = client.post("/users", json=payload, headers=admin_headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_seeded_admin_starts_with_admin_and_must_change(client, monkeypatch):
    db = SessionLocal()
    db.query(User).delete()
    db.commit()
    db.close()
    monkeypatch.delenv("SEED_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "chef@example.org")
    monkeypatch.setenv("SEED_EXAMPLE_VLANS", "0")
    seed.main()

    response = client.post("/auth/login", data={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    # Bis zum eigenen Passwort ist nur /auth/me und der Passwortwechsel erlaubt
    blocked = client.get("/devices", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["detail"] == PASSWORD_CHANGE_REQUIRED
    me = client.get("/auth/me", headers=headers).json()
    assert me["email"] == "chef@example.org" and me["must_change_password"] is True

    changed = client.post(
        "/auth/change-password",
        json={"current_password": "admin", "new_password": "ganz-geheim-1"},
        headers=headers,
    )
    assert changed.status_code == 200 and changed.json()["must_change_password"] is False
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/devices", headers=new_headers).status_code == 200
    assert client.get("/vlans", headers=new_headers).json() == []
    assert client.get("/devices", headers=headers).status_code == 401


def test_forgot_password_notifies_admin_without_revealing_accounts(client, admin_headers, sent_mails):
    _create_user(client, admin_headers)

    unknown = client.post("/auth/forgot-password", json={"username": "niemand", "email": "x@example.com"})
    wrong_email = client.post("/auth/forgot-password", json={"username": "anna", "email": "falsch@example.com"})
    match = client.post("/auth/forgot-password", json={"username": "Anna", "email": "ANNA@example.com"})
    assert unknown.status_code == wrong_email.status_code == match.status_code == 202
    assert unknown.json() == wrong_email.json() == match.json()

    assert len(sent_mails) == 1
    mail = sent_mails[0]
    assert mail["to"] == ["admin@example.com"]  # ohne ADMIN_NOTIFY_EMAIL: alle aktiven Admins
    assert "anna" in mail["subject"]
    assert "Benutzername: anna" in mail["body"] and "E-Mail:       anna@example.com" in mail["body"]

    # Sperrfrist: kein zweites Mal innerhalb von 15 Minuten
    client.post("/auth/forgot-password", json={"username": "anna", "email": "anna@example.com"})
    assert len(sent_mails) == 1

    users = {user["username"]: user for user in client.get("/users", headers=admin_headers).json()}
    assert users["anna"]["password_reset_requested_at"] is not None
    assert users["admin"]["password_reset_requested_at"] is None


def test_forgot_password_uses_configured_recipient(client, admin_headers, sent_mails, monkeypatch):
    monkeypatch.setattr(account_mails, "ADMIN_NOTIFY_EMAIL", "chef@example.org, vertretung@example.org")
    _create_user(client, admin_headers)
    client.post("/auth/forgot-password", json={"username": "anna", "email": "anna@example.com"})
    assert sent_mails[0]["to"] == ["chef@example.org", "vertretung@example.org"]


def test_forgot_password_ignores_deactivated_accounts(client, admin_headers, sent_mails):
    user = _create_user(client, admin_headers)
    client.patch(f"/users/{user['id']}", json={"is_active": False}, headers=admin_headers)
    assert client.post(
        "/auth/forgot-password", json={"username": "anna", "email": "anna@example.com"}
    ).status_code == 202
    assert sent_mails == []


def test_temporary_password_by_mail(client, admin_headers, sent_mails):
    # Ohne Passwort angelegt: niemand kann sich anmelden, bis das Einmal-Passwort kommt
    user = _create_user(client, admin_headers, password=None)
    assert user["must_change_password"] is True
    client.post("/auth/forgot-password", json={"username": "anna", "email": "anna@example.com"})

    result = client.post(f"/users/{user['id']}/temporary-password", headers=admin_headers)
    assert result.status_code == 200
    assert result.json() == {"email": "anna@example.com", "email_sent": True, "temporary_password": None}

    mail = sent_mails[-1]
    assert mail["to"] == ["anna@example.com"]
    temporary = TEMPORARY_PASSWORD_RE.search(mail["body"]).group(1)
    assert re.fullmatch(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", temporary)

    # Die offene Anfrage ist damit erledigt
    users = {u["username"]: u for u in client.get("/users", headers=admin_headers).json()}
    assert users["anna"]["password_reset_requested_at"] is None

    first_login = client.post("/auth/login", data={"username": "anna", "password": temporary})
    assert first_login.json()["must_change_password"] is True
    headers = activate(client, "anna", temporary, "anna-eigen-1")
    assert client.get("/devices", headers=headers).status_code == 200
    assert client.post("/auth/login", data={"username": "anna", "password": temporary}).status_code == 401


def test_temporary_password_shown_once_when_mail_fails(client, admin_headers, sent_mails):
    sent_mails.mail_ok = False
    user = _create_user(client, admin_headers)
    old_headers = activate(client, "anna", "anna-start-1", "anna-eigen-1")

    result = client.post(f"/users/{user['id']}/temporary-password", headers=admin_headers).json()
    assert result["email_sent"] is False and result["temporary_password"]

    # Altes Passwort und alte Sitzung gelten nicht mehr
    assert client.get("/auth/me", headers=old_headers).status_code == 401
    assert client.post("/auth/login", data={"username": "anna", "password": "anna-eigen-1"}).status_code == 401
    login(client, "anna", result["temporary_password"])


def test_temporary_password_rules(client, admin_headers, sent_mails):
    admin_id = client.get("/auth/me", headers=admin_headers).json()["id"]
    assert client.post(f"/users/{admin_id}/temporary-password", headers=admin_headers).status_code == 400

    user = _create_user(client, admin_headers)
    client.patch(f"/users/{user['id']}", json={"is_active": False}, headers=admin_headers)
    assert client.post(f"/users/{user['id']}/temporary-password", headers=admin_headers).status_code == 400

    _create_user(client, admin_headers, username="bert", role="operator")
    bert_headers = activate(client, "bert", "anna-start-1", "bert-eigen-1")
    assert client.post(f"/users/{user['id']}/temporary-password", headers=bert_headers).status_code == 403
    assert sent_mails == []


def test_admin_set_password_forces_change_and_ends_sessions(client, admin_headers):
    user = _create_user(client, admin_headers)
    old_headers = activate(client, "anna", "anna-start-1", "anna-eigen-1")

    assert client.patch(
        f"/users/{user['id']}", json={"password": "vom-admin-1"}, headers=admin_headers
    ).json()["must_change_password"] is True
    assert client.get("/auth/me", headers=old_headers).status_code == 401
    assert client.post(
        "/auth/login", data={"username": "anna", "password": "vom-admin-1"}
    ).json()["must_change_password"] is True

    # Das eigene Passwort aendert der Admin unter "Mein Konto" (mit dem aktuellen Passwort)
    admin_id = client.get("/auth/me", headers=admin_headers).json()["id"]
    assert client.patch(f"/users/{admin_id}", json={"password": "anderes-pw-1"}, headers=admin_headers).status_code == 400


def test_add_missing_columns_upgrades_old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alt.db'}")
    with engine.begin() as conn:
        # users-Tabelle so, wie sie vor den Passwort-Funktionen angelegt wurde
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL UNIQUE, "
            "email VARCHAR(255) NOT NULL UNIQUE, hashed_password VARCHAR(255) NOT NULL, "
            "role VARCHAR(8) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO users VALUES (1, 'admin', 'a@example.com', 'x', 'admin', 1, '2026-10-01 10:00:00')"
        ))
    Base.metadata.create_all(bind=engine)

    added = add_missing_columns(engine)
    assert sorted(added) == [
        "users.must_change_password", "users.password_reset_requested_at", "users.token_version"
    ]
    assert add_missing_columns(engine) == []
    with engine.connect() as conn:
        row = conn.execute(text("SELECT must_change_password, token_version FROM users")).one()
    assert tuple(row) == (0, 0)
    assert "token_version" in {c["name"] for c in inspect(engine).get_columns("users")}
