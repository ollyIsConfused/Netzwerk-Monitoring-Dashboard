from shared.database import SessionLocal
from shared.models import AlertEvent, AlertLevel, MetricSample, MetricStatus

from .conftest import activate


def _create_viewer(client, admin_headers):
    client.post(
        "/users",
        json={"username": "viewer", "email": "viewer@example.com", "password": "viewer-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    return activate(client, "viewer", "viewer-pass-1", "viewer-eigen-1")


def test_vlans_require_login(client):
    assert client.get("/vlans").status_code == 401


def test_vlan_crud(client, admin_headers):
    created = client.post("/vlans", json={"name": "Server", "tag": 30}, headers=admin_headers)
    assert created.status_code == 201
    vlan_id = created.json()["id"]

    assert client.post("/vlans", json={"name": "Doppelt", "tag": 30}, headers=admin_headers).status_code == 409
    assert client.post("/vlans", json={"name": "Ungueltig", "tag": 5000}, headers=admin_headers).status_code == 422

    updated = client.patch(f"/vlans/{vlan_id}", json={"name": "DMZ", "description": "Webserver"}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json()["name"] == "DMZ" and updated.json()["tag"] == 30

    device = client.post(
        "/devices",
        json={"name": "web", "ip_address": "192.168.30.15", "device_type": "webserver", "vlan_id": vlan_id},
        headers=admin_headers,
    ).json()

    assert client.delete(f"/vlans/{vlan_id}", headers=admin_headers).status_code == 204
    # Das Geraet bleibt, ist aber keinem VLAN mehr zugeordnet
    assert client.get(f"/devices/{device['id']}", headers=admin_headers).json()["vlan_id"] is None


def test_device_validation_and_config(client, admin_headers):
    bad_ip = client.post(
        "/devices", json={"name": "x", "ip_address": "300.1.1.1 ;rm", "device_type": "other"}, headers=admin_headers
    )
    assert bad_ip.status_code == 422

    missing_vlan = client.post(
        "/devices", json={"name": "x", "ip_address": "10.0.0.1", "device_type": "other", "vlan_id": 999},
        headers=admin_headers,
    )
    assert missing_vlan.status_code == 400

    device = client.post(
        "/devices",
        json={"name": "switch", "ip_address": "switch.lan", "device_type": "switch", "snmp_enabled": True,
              "snmp_community": "geheim", "snmp_interfaces": "1,2"},
        headers=admin_headers,
    )
    assert device.status_code == 201
    device_id = device.json()["id"]
    assert "snmp_community" not in device.json()

    config = client.get(f"/devices/{device_id}/config", headers=admin_headers)
    assert config.status_code == 200 and config.json()["snmp_community"] == "geheim"

    viewer_headers = _create_viewer(client, admin_headers)
    assert client.get(f"/devices/{device_id}/config", headers=viewer_headers).status_code == 403
    assert client.get(f"/devices/{device_id}", headers=viewer_headers).status_code == 200

    patched = client.patch(f"/devices/{device_id}", json={"name": "core-switch", "snmp_version": None},
                           headers=admin_headers)
    assert patched.status_code == 200 and patched.json()["name"] == "core-switch"
    assert client.get(f"/devices/{device_id}/config", headers=admin_headers).json()["snmp_version"] == "2c"


def test_delete_device_with_metrics_and_alerts(client, admin_headers):
    device_id = client.post(
        "/devices", json={"name": "nas", "ip_address": "192.168.50.25", "device_type": "nas"}, headers=admin_headers
    ).json()["id"]

    db = SessionLocal()
    db.add(MetricSample(device_id=device_id, metric_name="reachable", value=1.0, status=MetricStatus.ok))
    db.add(AlertEvent(device_id=device_id, metric_name="reachable", level=AlertLevel.critical, message="weg"))
    db.commit()
    db.close()

    assert client.delete(f"/devices/{device_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/devices/{device_id}", headers=admin_headers).status_code == 404
    assert client.get("/alerts", headers=admin_headers).json() == []


def test_threshold_crud(client, admin_headers):
    device_id = client.post(
        "/devices", json={"name": "pihole", "ip_address": "192.168.20.10", "device_type": "dns_server"},
        headers=admin_headers,
    ).json()["id"]
    base = f"/devices/{device_id}/thresholds"

    created = client.post(base, json={"metric_name": "latency_ms", "warning_max": 50, "critical_max": 200},
                          headers=admin_headers)
    assert created.status_code == 201
    rule_id = created.json()["id"]

    assert client.post(base, json={"metric_name": "latency_ms"}, headers=admin_headers).status_code == 409

    updated = client.patch(f"{base}/{rule_id}", json={"warning_max": 80, "critical_max": None}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json()["warning_max"] == 80 and updated.json()["critical_max"] is None

    viewer_headers = _create_viewer(client, admin_headers)
    assert client.delete(f"{base}/{rule_id}", headers=viewer_headers).status_code == 403
    assert client.delete(f"{base}/{rule_id}", headers=admin_headers).status_code == 204
    assert client.get(base, headers=admin_headers).json() == []


def test_alert_lifecycle_via_collector(client, admin_headers):
    device_id = client.post(
        "/devices", json={"name": "router", "ip_address": "192.168.178.66", "device_type": "router"},
        headers=admin_headers,
    ).json()["id"]
    client.post(f"/devices/{device_id}/thresholds",
                json={"metric_name": "reachable", "critical_min": 0, "consecutive_breaches_required": 2},
                headers=admin_headers)
    collector = {"Authorization": "Bearer test-collector-token"}

    def push(value):
        response = client.post("/collector/metrics", headers=collector,
                               json={"samples": [{"device_id": device_id, "metric_name": "reachable", "value": value}]})
        assert response.status_code == 202, response.text

    push(0)
    assert client.get("/alerts", params={"active_only": True}, headers=admin_headers).json() == []
    push(0)  # zweite Messung in Folge -> Alarm
    active = client.get("/alerts", params={"active_only": True}, headers=admin_headers).json()
    assert [a["level"] for a in active] == ["critical"]

    push(1)  # wieder erreichbar -> Alarm erledigt, "behoben" nur in der Historie
    assert client.get("/alerts", params={"active_only": True}, headers=admin_headers).json() == []
    history = client.get("/alerts", headers=admin_headers).json()
    assert [a["level"] for a in history] == ["recovered", "critical"]
    assert history[1]["resolved_at"] is not None
