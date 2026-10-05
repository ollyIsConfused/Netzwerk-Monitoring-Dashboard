from datetime import datetime

from shared.database import SessionLocal
from shared.models import AlertEvent, AlertLevel, Device, DeviceType

from .conftest import ADMIN_PASSWORD, activate, login


def test_change_password(client, admin_headers):
    wrong = client.post(
        "/auth/change-password",
        json={"current_password": "falsch", "new_password": "neues-pass-1"},
        headers=admin_headers,
    )
    assert wrong.status_code == 400

    same = client.post(
        "/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD},
        headers=admin_headers,
    )
    assert same.status_code == 400

    too_short = client.post(
        "/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "kurz"},
        headers=admin_headers,
    )
    assert too_short.status_code == 422

    ok = client.post(
        "/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "neues-pass-1"},
        headers=admin_headers,
    )
    assert ok.status_code == 200
    assert client.post("/auth/login", data={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 401
    login(client, "admin", "neues-pass-1")

    # Andere Sitzungen sind abgemeldet, die eigene bekommt ein neues Token
    assert client.get("/auth/me", headers=admin_headers).status_code == 401
    new_headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get("/auth/me", headers=new_headers).status_code == 200


def test_create_user_and_roles(client, admin_headers):
    created = client.post(
        "/users",
        json={"username": "anna", "email": "anna@example.com", "password": "anna-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert created.json()["role"] == "viewer"

    duplicate = client.post(
        "/users",
        json={"username": "anna", "email": "other@example.com", "password": "anna-pass-1"},
        headers=admin_headers,
    )
    assert duplicate.status_code == 409

    bad_email = client.post(
        "/users",
        json={"username": "bert", "email": "kein-mail", "password": "bert-pass-1"},
        headers=admin_headers,
    )
    assert bad_email.status_code == 422

    viewer_headers = activate(client, "anna", "anna-pass-1", "anna-eigen-1")
    assert client.get("/users", headers=viewer_headers).status_code == 403
    assert client.get("/auth/me", headers=viewer_headers).json()["username"] == "anna"


def test_last_admin_is_protected(client, admin_headers):
    admin_id = client.get("/auth/me", headers=admin_headers).json()["id"]

    assert client.patch(f"/users/{admin_id}", json={"role": "viewer"}, headers=admin_headers).status_code == 400
    assert client.patch(f"/users/{admin_id}", json={"is_active": False}, headers=admin_headers).status_code == 400
    assert client.delete(f"/users/{admin_id}", headers=admin_headers).status_code == 400

    second = client.post(
        "/users",
        json={"username": "zweit", "email": "zweit@example.com", "password": "zweit-pass-1", "role": "admin"},
        headers=admin_headers,
    ).json()
    # Mit einem zweiten Admin darf der erste herabgestuft werden
    assert client.patch(f"/users/{admin_id}", json={"role": "operator"}, headers=admin_headers).status_code == 200

    second_headers = activate(client, "zweit", "zweit-pass-1", "zweit-eigen-1")
    assert client.patch(f"/users/{second['id']}", json={"role": "viewer"}, headers=second_headers).status_code == 400


def test_admin_resets_password_and_deactivates(client, admin_headers):
    user = client.post(
        "/users",
        json={"username": "carl", "email": "carl@example.com", "password": "carl-pass-1", "role": "operator"},
        headers=admin_headers,
    ).json()

    assert client.patch(f"/users/{user['id']}", json={"password": "neu-carl-1"}, headers=admin_headers).status_code == 200
    login(client, "carl", "neu-carl-1")

    assert client.patch(f"/users/{user['id']}", json={"is_active": False}, headers=admin_headers).status_code == 200
    assert client.post("/auth/login", data={"username": "carl", "password": "neu-carl-1"}).status_code == 401


def test_delete_user_keeps_acknowledged_alerts(client, admin_headers):
    user = client.post(
        "/users",
        json={"username": "dora", "email": "dora@example.com", "password": "dora-pass-1", "role": "operator"},
        headers=admin_headers,
    ).json()

    db = SessionLocal()
    device = Device(name="sw1", ip_address="10.0.0.1", device_type=DeviceType.switch)
    db.add(device)
    db.flush()
    db.add(AlertEvent(device_id=device.id, metric_name="reachable", level=AlertLevel.critical, message="x",
                      acknowledged_by_id=user["id"], acknowledged_at=datetime.utcnow()))
    db.commit()
    db.close()

    assert client.delete(f"/users/{user['id']}", headers=admin_headers).status_code == 204
    alerts = client.get("/alerts", headers=admin_headers).json()
    assert len(alerts) == 1 and alerts[0]["acknowledged_at"] is not None


def test_cannot_delete_own_account(client, admin_headers):
    admin_id = client.get("/auth/me", headers=admin_headers).json()["id"]
    client.post(
        "/users",
        json={"username": "erik", "email": "erik@example.com", "password": "erik-pass-1", "role": "admin"},
        headers=admin_headers,
    )
    assert client.delete(f"/users/{admin_id}", headers=admin_headers).status_code == 400
