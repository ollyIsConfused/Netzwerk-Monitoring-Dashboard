"""Tests fuer die SNMP-Zugangsdaten des Collectors (ohne Netzwerk).

Ausfuehren (aus dem Projektordner, Python 3.9-3.11):
    python -m venv .venv-collector && .venv-collector/bin/pip install -r collector/requirements.txt pytest
    PYTHONPATH=. .venv-collector/bin/pytest collector/tests
"""
from datetime import datetime

from pysnmp.hlapi import (
    CommunityData,
    UsmUserData,
    usmAesCfb128Protocol,
    usmDESPrivProtocol,
    usmHMACSHAAuthProtocol,
    usmNoPrivProtocol,
)

from collector import main
from collector.snmp_client import snmp_auth


def test_community_versions():
    assert snmp_auth("2c", None) is None
    v1 = snmp_auth("1", "geheim").pysnmp_auth()
    v2c = snmp_auth("2c", "geheim").pysnmp_auth()
    assert isinstance(v1, CommunityData) and v1.mpModel == 0
    assert isinstance(v2c, CommunityData) and v2c.mpModel == 1


def test_v3_auth_priv_and_auth_only():
    # Wie beim TP-Link TL-SG3210: SHA + DES
    des = snmp_auth("3", None, "Monitoring", "sha", "authpass12345678", "des", "privpass1234567").pysnmp_auth()
    assert isinstance(des, UsmUserData)
    assert des.userName == "Monitoring"
    assert des.authProtocol == usmHMACSHAAuthProtocol and des.privProtocol == usmDESPrivProtocol

    aes = snmp_auth("3", None, "monitoring", "sha", "authpass12345678", "aes", "privpass1234567").pysnmp_auth()
    assert aes.privProtocol == usmAesCfb128Protocol

    auth_only = snmp_auth("3", None, "monitoring", "sha", "authpass12345678").pysnmp_auth()
    assert auth_only.privProtocol == usmNoPrivProtocol


def test_v3_incomplete_is_skipped():
    assert snmp_auth("3", "community-gilt-nicht", None, "sha", "authpass12345678") is None
    assert snmp_auth("3", None, "monitoring", None, "authpass12345678") is None
    assert snmp_auth("3", None, "monitoring", "rot13", "authpass12345678") is None
    assert snmp_auth("3", None, "monitoring", "sha", None) is None
    assert snmp_auth("3", None, "monitoring", "sha", "authpass12345678", "des", None) is None
    assert snmp_auth("3", None, "monitoring", "sha", "authpass12345678", "blowfish", "privpass1234567") is None


def test_secrets_never_in_repr():
    auth = snmp_auth("3", None, "monitoring", "sha", "authpass12345678", "des", "privpass1234567")
    assert "authpass" not in repr(auth) and "privpass" not in repr(auth)
    assert "geheim" not in repr(snmp_auth("2c", "geheim"))


def _device(**overrides):
    values = dict(
        id=1, name="Switch", ip_address="192.168.178.2", device_type="switch", snmp_enabled=True,
        snmp_community=None, snmp_version="3", snmp_port=161, snmp_interfaces="49153,49154",
        snmp_v3_user="Monitoring", snmp_v3_auth_protocol="sha", snmp_v3_auth_password="authpass12345678",
        snmp_v3_priv_protocol="des", snmp_v3_priv_password="privpass1234567",
    )
    values.update(overrides)
    return main.CollectorDevice(**values)


def test_poll_snmp_uses_v3_credentials(monkeypatch):
    calls = []

    def fake_poll(ip, auth, if_index, port):
        calls.append((ip, auth.version, auth.user, if_index))
        return {f"if{if_index}_oper_status": 1.0}

    monkeypatch.setattr(main, "poll_interface_counters", fake_poll)
    samples = main._poll_snmp(_device(), datetime(2026, 10, 6, 12, 0))
    assert calls == [("192.168.178.2", "3", "Monitoring", 49153), ("192.168.178.2", "3", "Monitoring", 49154)]
    assert {s["metric_name"] for s in samples} == {"if49153_oper_status", "if49154_oper_status"}

    # Unvollstaendige v3-Angaben: keine Abfrage
    calls.clear()
    assert main._poll_snmp(_device(snmp_v3_auth_password=None), datetime(2026, 10, 6, 12, 0)) == []
    assert calls == []


def test_fetch_devices_ignores_unknown_fields(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            item = {k: v for k, v in vars(_device()).items()}
            item["feld_aus_neuerem_backend"] = "egal"
            return [item]

    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: Response())
    devices = main.fetch_devices()
    assert devices[0].snmp_v3_user == "Monitoring"

    # Aelteres Backend ohne v3-Felder
    class OldResponse(Response):
        def json(self):
            return [{k: v for k, v in vars(_device()).items() if not k.startswith("snmp_v3_")}]

    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: OldResponse())
    assert main.fetch_devices()[0].snmp_v3_user is None
