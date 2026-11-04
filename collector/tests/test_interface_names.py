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


def _setup(monkeypatch, names, single=None):
    """names: was die Schnittstellentabelle liefert; single: Antworten auf Einzelabfragen."""
    main._names_checked.clear()
    main._names_reported.clear()
    walks, singles, pushes = [], [], []
    monkeypatch.setattr(main, "poll_interface_counters", lambda ip, auth, index, port: {f"if{index}_oper_status": 1.0})

    def fake_walk(ip, auth, port):
        walks.append(ip)
        return dict(names)

    def fake_single(ip, auth, indexes, port):
        singles.append(indexes)
        return {index: (single or {})[index] for index in indexes if index in (single or {})}

    monkeypatch.setattr(main, "discover_interface_names", fake_walk)
    monkeypatch.setattr(main, "poll_interface_names", fake_single)
    monkeypatch.setattr(main, "push_interface_names", lambda device_id, found: pushes.append((device_id, found)))
    return walks, singles, pushes


TP_LINK = {1: "Vlan-interface1", **{49152 + port: f"gigabitEthernet 1/0/{port}" for port in range(1, 11)}}


def test_all_ports_are_discovered_once_and_pushed_once(monkeypatch):
    walks, singles, pushes = _setup(monkeypatch, TP_LINK)
    now = datetime(2026, 11, 4, 12, 0)

    main._poll_snmp(_device(), now)
    main._poll_snmp(_device(), now)
    assert len(walks) == 1  # zweite Runde innerhalb der Stunde: keine Abfrage
    assert singles == []  # alle eingetragenen Ports waren in der Tabelle
    assert pushes == [(5, TP_LINK)]  # alle 10 Ports, nicht nur die zwei eingetragenen

    # Neuer Port in der Liste: sofort neu lesen
    main._poll_snmp(_device(snmp_interfaces="49153,49154,49155"), now)
    assert len(walks) == 2


def test_missing_ports_are_asked_individually(monkeypatch):
    # Manche Geraete geben die Tabelle nicht vollstaendig heraus
    walks, singles, pushes = _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1"}, single={49154: "gigabitEthernet 1/0/2"})
    main._poll_snmp(_device(), datetime(2026, 11, 4, 12, 0))
    assert singles == [[49154]]
    assert pushes == [(5, {49153: "gigabitEthernet 1/0/1", 49154: "gigabitEthernet 1/0/2"})]


def test_unchanged_names_are_not_pushed_again(monkeypatch):
    walks, _singles, pushes = _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1"})
    main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 11, 4, 12, 0))
    main._names_checked.clear()  # Stunde ist um
    main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 11, 4, 13, 0))
    assert len(walks) == 2 and len(pushes) == 1


def test_old_backend_without_endpoint_does_not_break_polling(monkeypatch):
    _setup(monkeypatch, {49153: "gigabitEthernet 1/0/1"})

    def not_found(device_id, names):
        raise requests.HTTPError("404 Not Found")

    monkeypatch.setattr(main, "push_interface_names", not_found)
    samples = main._poll_snmp(_device(snmp_interfaces="49153"), datetime(2026, 11, 4, 12, 0))
    assert [s["metric_name"] for s in samples] == ["if49153_oper_status"]


def test_ports_are_discovered_even_before_any_are_chosen(monkeypatch):
    # Neues Geraet ohne eingetragene Ports: trotzdem die Liste zum Anhaken holen
    walks, _singles, pushes = _setup(monkeypatch, TP_LINK)
    monkeypatch.setattr(main, "poll_interface_counters", lambda *args: {})
    main._poll_snmp(_device(snmp_interfaces=None), datetime(2026, 11, 4, 12, 0))
    assert len(walks) == 1 and pushes == [(5, TP_LINK)]


def test_unreachable_device_with_chosen_ports_is_not_walked(monkeypatch):
    walks, _singles, _pushes = _setup(monkeypatch, {})
    monkeypatch.setattr(main, "poll_interface_counters", lambda *args: {})
    assert main._poll_snmp(_device(), datetime(2026, 11, 4, 12, 0)) == []
    assert walks == []
