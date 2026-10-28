"""Portnamen: "Port 1" statt "Interface 49153", eigene Namen haben Vorrang."""
from shared.interfaces import friendly_interface_name

COLLECTOR = {"Authorization": "Bearer test-collector-token"}


def test_friendly_interface_name():
    assert friendly_interface_name("gigabitEthernet 1/0/1") == "Port 1"
    assert friendly_interface_name("gigabitEthernet 1/0/10") == "Port 10"
    assert friendly_interface_name("Gi2/0/3") == "Port 2/3"  # zweiter Switch im Stapel
    assert friendly_interface_name("eth0.20") == "eth0.20"
    assert friendly_interface_name("Vlan-interface1") == "Vlan-interface1"


def _switch(client, admin_headers, **extra):
    response = client.post(
        "/devices",
        json={"name": "Switch", "ip_address": "192.168.178.81", "device_type": "switch", "snmp_enabled": True,
              "snmp_version": "2c", "snmp_community": "test", "snmp_interfaces": "49153,49154", **extra},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_collector_names_become_port_labels(client, admin_headers):
    device = _switch(client, admin_headers)
    assert device["interface_labels"] == {}

    response = client.post(
        "/collector/interface-names",
        json={"device_id": device["id"], "names": {"49153": "gigabitEthernet 1/0/1", "49154": "gigabitEthernet 1/0/2"}},
        headers=COLLECTOR,
    )
    assert response.status_code == 200, response.text
    shown = client.get(f"/devices/{device['id']}", headers=admin_headers).json()
    assert shown["interface_labels"] == {"49153": "Port 1", "49154": "Port 2"}

    # Spaetere Meldung fuer einen Index ergaenzt, ohne die anderen zu verlieren
    client.post("/collector/interface-names", json={"device_id": device["id"], "names": {"1": "Vlan-interface1"}},
                headers=COLLECTOR)
    config = client.get(f"/devices/{device['id']}/config", headers=admin_headers).json()
    assert config["snmp_interface_names"] == {
        "1": "Vlan-interface1", "49153": "gigabitEthernet 1/0/1", "49154": "gigabitEthernet 1/0/2",
    }


def test_manual_labels_override_and_can_be_cleared(client, admin_headers):
    device = _switch(client, admin_headers, snmp_interface_labels={"49153": "  Port 1 – FritzBox  ", "49154": " "})
    client.post("/collector/interface-names",
                json={"device_id": device["id"], "names": {"49153": "gigabitEthernet 1/0/1", "49154": "gigabitEthernet 1/0/2"}},
                headers=COLLECTOR)
    shown = client.get(f"/devices/{device['id']}", headers=admin_headers).json()
    assert shown["interface_labels"] == {"49153": "Port 1 – FritzBox", "49154": "Port 2"}
    config = client.get(f"/devices/{device['id']}/config", headers=admin_headers).json()
    assert config["snmp_interface_labels"] == {"49153": "Port 1 – FritzBox"}

    response = client.patch(f"/devices/{device['id']}", json={"snmp_interface_labels": {}}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["interface_labels"] == {"49153": "Port 1", "49154": "Port 2"}


def test_label_validation(client, admin_headers):
    device = _switch(client, admin_headers)
    for labels in ({"abc": "Port"}, {"49153": "x" * 41}):
        response = client.patch(f"/devices/{device['id']}", json={"snmp_interface_labels": labels}, headers=admin_headers)
        assert response.status_code == 422, labels


def test_interface_names_endpoint_requires_collector_token(client, admin_headers):
    device = _switch(client, admin_headers)
    payload = {"device_id": device["id"], "names": {"49153": "gigabitEthernet 1/0/1"}}
    assert client.post("/collector/interface-names", json=payload).status_code == 401
    assert client.post("/collector/interface-names", json=payload, headers=admin_headers).status_code == 401
    assert client.post("/collector/interface-names", json={"device_id": 999, "names": {}},
                       headers=COLLECTOR).status_code == 404
