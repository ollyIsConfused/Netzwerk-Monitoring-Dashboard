"""Schnittstellennamen: vom Geraet lesen (ifName, sonst ifDescr) und nur bei Bedarf melden."""
from datetime import datetime

import requests

from collector import main, snmp_client
from collector.snmp_client import OID_IF_DESCR, OID_IF_NAME, snmp_auth

AUTH = snmp_auth("3", None, "Monitoring", "sha", "authpass12345678", "des", "privpass1234567")


def test_poll_interface_names_falls_back_to_ifdescr(monkeypatch):
    requested = []

    def fake_strings(ip, auth, oids, port):
        requested.append(oids)
        known = {
            f"{OID_IF_NAME}.49153": "gigabitEthernet 1/0/1",
            f"{OID_IF_DESCR}.7": "eth0.20",
        }
        return {oid: known[oid] for oid in oids if oid in known}

    monkeypatch.setattr(snmp_client, "snmp_get_strings", fake_strings)
    names = snmp_client.poll_interface_names("192.168.178.81", AUTH, [49153, 7])
    assert names == {49153: "gigabitEthernet 1/0/1", 7: "eth0.20"}
    # ifDescr nur fuer den Index, der kein ifName hatte
    assert requested == [[f"{OID_IF_NAME}.49153", f"{OID_IF_NAME}.7"], [f"{OID_IF_DESCR}.7"]]


def _device(**overrides):
    values = dict(
        id=5, name="Switch", ip_address="192.168.178.81", device_type="switch", snmp_enabled=True,
        snmp_community=None, snmp_version="3", snmp_port=161, snmp_interfaces="49153,49154",
        snmp_v3_user="Monitoring", snmp_v3_auth_protocol="sha", snmp_v3_auth_password="authpass12345678",
        snmp_v3_priv_protocol="des", snmp_v3_priv_password="privpass1234567",
    )
    values.update(overrides)
    return main.CollectorDevice(**values)


def _setup(monkeypatch, names):
    main._names_checked.clear()
    main._names_reported.clear()
    lookups, pushes = [], []
    monkeypatch.setattr(main, "poll_interface_counters", lambda ip, auth, index, port: {f"if{index}_oper_status": 1.0})

    def fake_names(ip, auth, indexes, port):
        lookups.append(indexes)
        return dict(names)

    monkeypatch.setattr(main, "poll_interface_names", fake_names)
    monkeypatch.setattr(main, "push_interface_names", lambda device_id, found: pushes.append((device_id, found)))
    return lookups, pushes


def test_names_are_read_once_and_pushed_once(monkeypatch):
    lookups, pushes = _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1", 49154: "gigabitEthernet 1/0/2"})
    now = datetime(2026, 10, 28, 12, 0)

    main._poll_snmp(_device(), now)
    main._poll_snmp(_device(), now)
    assert lookups == [[49153, 49154]]  # zweite Runde innerhalb der Stunde: keine Abfrage
    assert pushes == [(5, {49153: "gigabitEthernet 1/0/1", 49154: "gigabitEthernet 1/0/2"})]

    # Neuer Port in der Liste: sofort neu lesen
    main._poll_snmp(_device(snmp_interfaces="49153,49154,49155"), now)
    assert lookups[-1] == [49153, 49154, 49155]


def test_unchanged_names_are_not_pushed_again(monkeypatch):
    lookups, pushes = _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1"})
    main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 10, 28, 12, 0))
    main._names_checked.clear()  # Stunde ist um
    main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 10, 28, 13, 0))
    assert len(lookups) == 2 and len(pushes) == 1


def test_old_backend_without_endpoint_does_not_break_polling(monkeypatch):
    _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1"})

    def not_found(device_id, names):
        raise requests.HTTPError("404 Not Found")

    monkeypatch.setattr(main, "push_interface_names", not_found)
    samples = main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 10, 28, 12, 0))
    assert [s["metric_name"] for s in samples] == ["if49153_oper_status"]


def test_unreachable_device_is_not_asked_for_names(monkeypatch):
    lookups, _pushes = _setup(monkeypatch, {})
    monkeypatch.setattr(main, "poll_interface_counters", lambda *args: {})
    assert main._poll_snmp(_device(), datetime(2026, 10, 28, 12, 0)) == []
    assert lookups == []
