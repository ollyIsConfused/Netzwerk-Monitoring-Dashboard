from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from shared.database import Base, add_missing_columns

from app import config
from app.device_status import is_stale
from app.routers.ws import _current_status_snapshot

COLLECTOR_HEADERS = {"Authorization": "Bearer test-collector-token"}


def _vlans(client, admin_headers, *tags):
    return {
        tag: client.post("/vlans", json={"name": f"VLAN {tag}", "tag": tag}, headers=admin_headers).json()["id"]
        for tag in tags
    }


def test_trunk_device_with_address_per_vlan(client, admin_headers):
    vlans = _vlans(client, admin_headers, 1, 20, 30, 50)
    router = {
        "name": "Router-Pi",
        "ip_address": "192.168.178.66",
        "device_type": "router",
        "port_mode": "trunk",
        "vlan_id": vlans[1],
        "tagged_vlan_ids": [vlans[20], vlans[30], vlans[50]],
    }
    created = client.post(
        "/devices",
        json={
            **router,
            "vlan_addresses": [
                {"vlan_id": vlans[50], "ip_address": "192.168.50.1"},
                {"vlan_id": vlans[20], "ip_address": " 192.168.20.1 "},
                {"vlan_id": vlans[30], "ip_address": "192.168.30.1"},
            ],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    device = created.json()
    # Nach VLAN-Tag sortiert, Leerzeichen entfernt
    assert device["vlan_addresses"] == [
        {"vlan_id": vlans[20], "ip_address": "192.168.20.1"},
        {"vlan_id": vlans[30], "ip_address": "192.168.30.1"},
        {"vlan_id": vlans[50], "ip_address": "192.168.50.1"},
    ]
    assert device["ip_address"] == "192.168.178.66"  # ueberwacht wird weiter die Haupt-IP

    def create(addresses):
        return client.post("/devices", json={**router, "vlan_addresses": addresses}, headers=admin_headers)

    # Adresse fuer das native (nicht getaggte) VLAN, doppelt, kein IP-Format
    assert create([{"vlan_id": vlans[1], "ip_address": "192.168.178.66"}]).status_code == 400
    assert create([{"vlan_id": vlans[20], "ip_address": "192.168.20.1"}] * 2).status_code == 400
    assert create([{"vlan_id": vlans[20], "ip_address": "router.local"}]).status_code == 422
    # IPv6 wird normalisiert
    assert create([{"vlan_id": vlans[20], "ip_address": "FD00::0001"}]).json()["vlan_addresses"] == [
        {"vlan_id": vlans[20], "ip_address": "fd00::1"}
    ]

    url = f"/devices/{device['id']}"
    # Nur die VLANs geaendert: Adressen der verbleibenden VLANs bleiben erhalten
    updated = client.patch(url, json={"tagged_vlan_ids": [vlans[20], vlans[50]]}, headers=admin_headers).json()
    assert updated["vlan_addresses"] == [
        {"vlan_id": vlans[20], "ip_address": "192.168.20.1"},
        {"vlan_id": vlans[50], "ip_address": "192.168.50.1"},
    ]
    # Eine neue Adressliste ersetzt die alte
    updated = client.patch(
        url, json={"vlan_addresses": [{"vlan_id": vlans[50], "ip_address": "192.168.50.254"}]}, headers=admin_headers
    ).json()
    assert updated["tagged_vlan_ids"] == [vlans[20], vlans[50]]
    assert updated["vlan_addresses"] == [{"vlan_id": vlans[50], "ip_address": "192.168.50.254"}]
    assert client.patch(
        url, json={"vlan_addresses": [{"vlan_id": vlans[30], "ip_address": "192.168.30.1"}]}, headers=admin_headers
    ).status_code == 400

    # Auch Uebersicht und Bearbeiten-Formular liefern die Adressen
    assert client.get("/devices/status", headers=admin_headers).json()[0]["device"]["vlan_addresses"] == [
        {"vlan_id": vlans[50], "ip_address": "192.168.50.254"}
    ]
    assert client.get(f"{url}/config", headers=admin_headers).json()["vlan_addresses"][0]["vlan_id"] == vlans[50]

    # Geloeschtes VLAN nimmt seine Adresse mit, Access-Port hat keine
    assert client.delete(f"/vlans/{vlans[50]}", headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).json()["vlan_addresses"] == []
    access = client.patch(url, json={"port_mode": "access"}, headers=admin_headers).json()
    assert access["tagged_vlan_ids"] == [] and access["vlan_addresses"] == []


def test_status_marks_stale_collector_data(client, admin_headers):
    device = client.post(
        "/devices", json={"name": "pihole", "ip_address": "192.168.20.10", "device_type": "dns_server"},
        headers=admin_headers,
    ).json()

    def push(minutes_ago):
        timestamp = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
        sample = {"device_id": device["id"], "metric_name": "reachable", "value": 1, "timestamp": timestamp}
        assert client.post("/collector/metrics", json={"samples": [sample]}, headers=COLLECTOR_HEADERS).status_code == 202

    def status():
        return client.get("/devices/status", headers=admin_headers).json()[0]

    # Noch nie gemessen: unbekannt, aber nicht "veraltet"
    assert status()["stale"] is False and status()["overall_status"] == "unknown"

    # Letzter Wert 10 Minuten alt (Collector gestoppt): letzter Stand bleibt sichtbar, Status unbekannt
    push(10)
    stale = status()
    assert stale["stale"] is True and stale["reachable"] is True and stale["overall_status"] == "unknown"
    assert _current_status_snapshot()[0]["status"] == "unknown"
    single = client.get(f"/devices/{device['id']}/status", headers=admin_headers)
    assert single.status_code == 200 and single.json()["stale"] is True
    assert client.get("/devices/9999/status", headers=admin_headers).status_code == 404

    push(0)
    fresh = status()
    assert fresh["stale"] is False and fresh["overall_status"] == "ok"
    assert _current_status_snapshot()[0]["status"] == "ok"


def test_agent_push_tracks_last_seen(client, admin_headers, monkeypatch):
    token = "a" * 32
    client.post(
        "/devices",
        json={"name": "nas", "ip_address": "192.168.50.25", "device_type": "nas", "agent_enabled": True,
              "agent_token": token},
        headers=admin_headers,
    )

    def status():
        return client.get("/devices/status", headers=admin_headers).json()[0]

    assert status()["agent_last_seen"] is None and status()["agent_stale"] is False

    pushed = client.post("/agent/push", json={"agent_token": token, "metrics": {"cpu_pct": 12.5, "disk_mnt_storage_pct": 40}})
    assert pushed.status_code == 202
    current = status()
    assert current["agent_last_seen"] is not None and current["agent_stale"] is False
    assert current["latest_metrics"]["disk_mnt_storage_pct"] == 40

    # Bleibt der Agent aus, meldet das Dashboard das
    monkeypatch.setattr(config, "STALE_AFTER_SECONDS", 0)
    assert status()["agent_stale"] is True

    assert client.post("/agent/push", json={"agent_token": "falsch", "metrics": {"cpu_pct": 1}}).status_code == 401
    # Metriknamen passen in die Datenbankspalte und enthalten keine Sonderzeichen
    for name in ("x" * 65, "mit leerzeichen", ""):
        assert client.post("/agent/push", json={"agent_token": token, "metrics": {name: 1}}).status_code == 422


def test_is_stale_handles_timezones(monkeypatch):
    monkeypatch.setattr(config, "STALE_AFTER_SECONDS", 60)
    now = datetime(2026, 10, 6, 12, 0, 0)
    assert is_stale(None, now) is False
    assert is_stale(now - timedelta(seconds=30), now) is False
    assert is_stale(now - timedelta(seconds=90), now) is True
    # Zeitstempel mit Zeitzone (z. B. 14:00 in Berlin = 12:00 UTC)
    berlin = timezone(timedelta(hours=2))
    assert is_stale(datetime(2026, 10, 6, 14, 0, 0, tzinfo=berlin), now) is False


def test_add_missing_columns_upgrades_devices(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alt.db'}")
    with engine.begin() as conn:
        # Tabellen so, wie sie vor den Adressen pro VLAN und der Agent-Zeit angelegt wurden
        conn.execute(text("CREATE TABLE vlans (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, "
                          "tag INTEGER NOT NULL UNIQUE, description TEXT)"))
        conn.execute(text(
            "CREATE TABLE devices (id INTEGER PRIMARY KEY, name VARCHAR(128) NOT NULL, ip_address VARCHAR(64) NOT NULL, "
            "device_type VARCHAR(10) NOT NULL, vlan_id INTEGER REFERENCES vlans(id), "
            "port_mode VARCHAR(8) DEFAULT 'access' NOT NULL, is_active BOOLEAN NOT NULL, snmp_enabled BOOLEAN NOT NULL, "
            "snmp_community VARCHAR(128), snmp_version VARCHAR(8) NOT NULL, snmp_port INTEGER NOT NULL, "
            "snmp_interfaces VARCHAR(255), agent_enabled BOOLEAN NOT NULL, agent_token VARCHAR(128), "
            "created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "CREATE TABLE device_tagged_vlans (device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE, "
            "vlan_id INTEGER REFERENCES vlans(id) ON DELETE CASCADE, PRIMARY KEY (device_id, vlan_id))"
        ))
        conn.execute(text("INSERT INTO vlans VALUES (1, 'DNS', 20, NULL)"))
        conn.execute(text(
            "INSERT INTO devices VALUES (1, 'Router-Pi', '192.168.178.66', 'router', NULL, 'trunk', 1, 0, NULL, '2c', "
            "161, NULL, 0, NULL, '2026-10-01 10:00:00')"
        ))
        conn.execute(text("INSERT INTO device_tagged_vlans VALUES (1, 1)"))
    Base.metadata.create_all(bind=engine)

    assert sorted(add_missing_columns(engine)) == ["device_tagged_vlans.ip_address", "devices.agent_last_push_at"]
    assert add_missing_columns(engine) == []
    with engine.connect() as conn:
        assert tuple(conn.execute(text("SELECT device_id, vlan_id, ip_address FROM device_tagged_vlans")).one()) == (
            1, 1, None
        )
