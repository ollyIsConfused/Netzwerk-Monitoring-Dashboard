"""Login-Bremse, angemeldeter WebSocket, abgeschaltete API-Beschreibung, kein offenes CORS."""
import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import LOGIN_MAX_FAILURES
from app.routers.ws import CLOSE_UNAUTHORIZED

from .conftest import ADMIN_PASSWORD, login


def _login(client, password, ip="203.0.113.7", username="admin"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers={"CF-Connecting-IP": ip},
    )


def test_login_blocked_after_too_many_failures(client):
    for _ in range(LOGIN_MAX_FAILURES):
        assert _login(client, "falsch").status_code == 401

    blocked = _login(client, ADMIN_PASSWORD)
    assert blocked.status_code == 429
    assert "Zu viele Fehlversuche" in blocked.json()["detail"]
    assert int(blocked.headers["Retry-After"]) > 0

    # Eine andere Adresse darf weiter - der Benutzername allein ist noch nicht gesperrt
    assert _login(client, ADMIN_PASSWORD, ip="198.51.100.9").status_code == 200


def test_username_blocked_even_with_changing_addresses(client):
    # Wer die Adresse faelscht (neue IP pro Versuch), wird ueber den Benutzernamen gebremst
    for attempt in range(LOGIN_MAX_FAILURES * 2):
        assert _login(client, "falsch", ip=f"192.0.2.{attempt}").status_code == 401
    assert _login(client, ADMIN_PASSWORD, ip="192.0.2.200").status_code == 429


def test_successful_login_resets_username_counter(client):
    for attempt in range(LOGIN_MAX_FAILURES * 2 - 1):
        assert _login(client, "falsch", ip=f"192.0.2.{attempt}").status_code == 401
    assert _login(client, ADMIN_PASSWORD, ip="192.0.2.100").status_code == 200
    # Nach der erfolgreichen Anmeldung zaehlt der Benutzername wieder von vorn
    assert _login(client, "falsch", ip="192.0.2.101").status_code == 401


def test_honeypot_counts_as_failure(client):
    for _ in range(LOGIN_MAX_FAILURES):
        response = client.post(
            "/auth/login",
            data={"username": "admin", "password": ADMIN_PASSWORD, "email": "bot@example.com"},
            headers={"CF-Connecting-IP": "203.0.113.50"},
        )
        assert response.status_code == 401
    assert _login(client, ADMIN_PASSWORD, ip="203.0.113.50").status_code == 429


def test_websocket_requires_login(client):
    with client.websocket_connect("/ws/status") as socket:
        socket.send_json({"type": "auth", "token": "kein-gueltiges-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == CLOSE_UNAUTHORIZED


@pytest.mark.parametrize("first_message", ["ping", b"\x00binaer", '{"type": "auth"}'])
def test_websocket_rejects_missing_auth_message(client, first_message):
    with client.websocket_connect("/ws/status") as socket:
        if isinstance(first_message, bytes):
            socket.send_bytes(first_message)
        else:
            socket.send_text(first_message)
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == CLOSE_UNAUTHORIZED


def test_websocket_sends_status_after_login(client, admin_headers):
    created = client.post("/devices", json={"name": "NAS", "ip_address": "192.168.50.25", "device_type": "nas"},
                          headers=admin_headers)
    assert created.status_code == 201, created.text
    token = admin_headers["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect("/ws/status") as socket:
        socket.send_json({"type": "auth", "token": token})
        message = socket.receive_json()
    assert message["type"] == "status"
    assert [device["name"] for device in message["devices"]] == ["NAS"]


def test_websocket_rejects_token_after_password_change(client, admin_headers):
    old_token = admin_headers["Authorization"].removeprefix("Bearer ")
    response = client.post(
        "/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "ganz-neues-pass-1"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    with client.websocket_connect("/ws/status") as socket:
        socket.send_json({"type": "auth", "token": old_token})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == CLOSE_UNAUTHORIZED


def test_api_docs_disabled_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_no_cors_headers_by_default(client):
    response = client.get("/health", headers={"Origin": "https://angreifer.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_login_still_works_normally(client):
    assert login(client, "admin", ADMIN_PASSWORD)["Authorization"].startswith("Bearer ")

