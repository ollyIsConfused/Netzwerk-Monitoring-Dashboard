COLLECTOR_HEADERS = {"Authorization": "Bearer test-collector-token"}

SWITCH_V3 = {
    "name": "TL-SG3210",
    "ip_address": "192.168.178.2",
    "device_type": "switch",
    "snmp_enabled": True,
    "snmp_version": "3",
    "snmp_interfaces": "49153,49154",
    "snmp_v3_user": "Monitoring",
    "snmp_v3_auth_protocol": "sha",
    "snmp_v3_auth_password": "authpass12345678",
    "snmp_v3_priv_protocol": "des",
    "snmp_v3_priv_password": "privpass1234567",
}
SECRET_FIELDS = ("snmp_v3_auth_password", "snmp_v3_priv_password", "snmp_community")


def test_v3_device_secrets_only_for_admin_config_and_collector(client, admin_headers):
    created = client.post("/devices", json=SWITCH_V3, headers=admin_headers)
    assert created.status_code == 201, created.text
    device_id = created.json()["id"]

    # Normale Ansichten (auch fuer Betrachter) enthalten keine Zugangsdaten
    for body in (created.json(), client.get(f"/devices/{device_id}", headers=admin_headers).json(),
                 client.get("/devices/status", headers=admin_headers).json()[0]["device"]):
        assert not any(field in body for field in SECRET_FIELDS)

    config = client.get(f"/devices/{device_id}/config", headers=admin_headers).json()
    assert config["snmp_version"] == "3" and config["snmp_v3_user"] == "Monitoring"
    assert config["snmp_v3_auth_password"] == "authpass12345678" and config["snmp_v3_priv_protocol"] == "des"

    polled = client.get("/collector/devices", headers=COLLECTOR_HEADERS).json()[0]
    assert polled["snmp_v3_auth_protocol"] == "sha" and polled["snmp_v3_priv_password"] == "privpass1234567"


def test_v3_validation(client, admin_headers):
    def create(**changes):
        return client.post("/devices", json={**SWITCH_V3, **changes}, headers=admin_headers)

    assert create(snmp_v3_user="  ").status_code == 400
    assert create(snmp_v3_auth_protocol=None).status_code == 400
    assert create(snmp_v3_auth_password="kurz").status_code == 400
    assert create(snmp_v3_auth_password="        ").status_code == 400
    assert create(snmp_v3_priv_password=None).status_code == 400
    assert create(snmp_v3_priv_password="kurz").status_code == 400
    assert create(snmp_v3_auth_protocol="rot13").status_code == 422
    assert create(snmp_v3_priv_protocol="blowfish").status_code == 422
    assert create(snmp_version="4").status_code == 422
    assert create(snmp_v3_auth_password="x" * 65).status_code == 422
    assert "Benutzername" in create(snmp_v3_user=None).json()["detail"]

    # Nur Anmeldung ohne Verschluesselung ist erlaubt, Benutzername wird getrimmt
    auth_only = create(snmp_v3_priv_protocol=None, snmp_v3_priv_password=None, snmp_v3_user=" Monitoring ")
    assert auth_only.status_code == 201
    # SNMP aus: unvollstaendige v3-Angaben stoeren nicht
    assert create(snmp_enabled=False, snmp_v3_user=None).status_code == 201

    config = client.get(f"/devices/{auth_only.json()['id']}/config", headers=admin_headers).json()
    assert config["snmp_v3_user"] == "Monitoring"


def test_switch_existing_device_to_v3(client, admin_headers):
    device = client.post(
        "/devices",
        json={"name": "Switch", "ip_address": "192.168.178.2", "device_type": "switch", "snmp_enabled": True,
              "snmp_community": "alt-community"},
        headers=admin_headers,
    ).json()
    url = f"/devices/{device['id']}"

    # Nur die Version umstellen reicht nicht
    assert client.patch(url, json={"snmp_version": "3"}, headers=admin_headers).status_code == 400
    assert client.get(f"{url}/config", headers=admin_headers).json()["snmp_version"] == "2c"

    v3_fields = {k: v for k, v in SWITCH_V3.items() if k.startswith("snmp_v3_")}
    assert client.patch(url, json={"snmp_version": "3", **v3_fields}, headers=admin_headers).status_code == 200
    # Verschluesselung wieder abschalten (null loescht den Wert)
    assert client.patch(url, json={"snmp_v3_priv_protocol": None}, headers=admin_headers).status_code == 200
    config = client.get(f"{url}/config", headers=admin_headers).json()
    assert config["snmp_version"] == "3" and config["snmp_v3_priv_protocol"] is None
