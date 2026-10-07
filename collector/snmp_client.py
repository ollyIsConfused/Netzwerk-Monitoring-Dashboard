"""Minimal synchronous SNMP GET client (v1, v2c and v3) built on pysnmp's classic hlapi.

Only what the collector needs: per-interface status and octet counters
(ifOperStatus, ifInOctets, ifOutOctets) for switches/routers.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Union

from pysnmp.hlapi import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    getCmd,
    usmAesCfb128Protocol,
    usmDESPrivProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
)

logger = logging.getLogger(__name__)

OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
OID_IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"

# Bezeichnungen wie im Backend (snmp_v3_auth_protocol / snmp_v3_priv_protocol)
AUTH_PROTOCOLS = {
    "md5": usmHMACMD5AuthProtocol,
    "sha": usmHMACSHAAuthProtocol,
    "sha224": usmHMAC128SHA224AuthProtocol,
    "sha256": usmHMAC192SHA256AuthProtocol,
    "sha384": usmHMAC256SHA384AuthProtocol,
    "sha512": usmHMAC384SHA512AuthProtocol,
}
PRIV_PROTOCOLS = {
    "des": usmDESPrivProtocol,
    "aes": usmAesCfb128Protocol,  # AES-128 nach RFC 3826, wie "AES" bei net-snmp und den meisten Switches
}

# Haeufige SNMP-v3-Fehler mit Hinweis, was am Geraet oder im Dashboard nicht passt
_V3_HINTS = {
    "UnknownUserName": "Benutzername am Gerät unbekannt (Groß-/Kleinschreibung beachten)",
    "WrongDigest": "Auth-Passwort oder Auth-Verfahren passt nicht",
    "DecryptionError": "Privacy-Passwort oder Verschlüsselung passt nicht",
    "UnsupportedSecLevel": "Sicherheitsstufe passt nicht zur Gruppe am Gerät",
    "NotInTimeWindow": "Zeitabgleich mit dem Gerät fehlgeschlagen",
}


@dataclass(frozen=True)
class SnmpAuth:
    """Zugangsdaten eines Geraets: v1/v2c mit Community, v3 mit Benutzer und Passwoertern."""

    version: str
    community: Optional[str] = None
    user: Optional[str] = None
    auth_protocol: Optional[str] = None
    auth_password: Optional[str] = None
    priv_protocol: Optional[str] = None
    priv_password: Optional[str] = None

    def pysnmp_auth(self) -> Union[CommunityData, UsmUserData]:
        if self.version != "3":
            # mpModel 0 = SNMPv1, 1 = SNMPv2c
            return CommunityData(self.community, mpModel=0 if self.version == "1" else 1)
        if self.priv_protocol:
            return UsmUserData(
                self.user,
                authKey=self.auth_password,
                privKey=self.priv_password,
                authProtocol=AUTH_PROTOCOLS[self.auth_protocol],
                privProtocol=PRIV_PROTOCOLS[self.priv_protocol],
            )
        return UsmUserData(self.user, authKey=self.auth_password, authProtocol=AUTH_PROTOCOLS[self.auth_protocol])

    def __repr__(self) -> str:
        # Nie Community oder Passwoerter in Logs/Tracebacks
        return f"SnmpAuth(version={self.version!r}, user={self.user!r})"


def snmp_auth(
    version: str,
    community: Optional[str],
    user: Optional[str] = None,
    auth_protocol: Optional[str] = None,
    auth_password: Optional[str] = None,
    priv_protocol: Optional[str] = None,
    priv_password: Optional[str] = None,
) -> Optional[SnmpAuth]:
    """Zugangsdaten aus der Geraete-Konfiguration; None, wenn die Angaben nicht reichen."""
    if version == "3":
        if not user or auth_protocol not in AUTH_PROTOCOLS or not auth_password:
            return None
        if priv_protocol and (priv_protocol not in PRIV_PROTOCOLS or not priv_password):
            return None
        return SnmpAuth("3", None, user, auth_protocol, auth_password, priv_protocol or None, priv_password or None)
    if not community:
        return None
    return SnmpAuth("1" if version == "1" else "2c", community)


# Ein SnmpEngine je Geraet (Adresse, Port, Zugangsdaten) fuer die ganze Laufzeit: SNMP v3 muss
# engineID, boots und time des Geraets so nur einmal erfragen, und Benutzer gleichen Namens mit
# unterschiedlichen Passwoertern auf verschiedenen Geraeten kommen sich nicht in die Quere.
_engines: dict[tuple[str, int, SnmpAuth], SnmpEngine] = {}


def _engine_for(ip_address: str, port: int, auth: SnmpAuth) -> SnmpEngine:
    key = (ip_address, port, auth)
    if key not in _engines:
        _engines[key] = SnmpEngine()
    return _engines[key]


def snmp_get_many(
    ip_address: str, auth: SnmpAuth, oids: list[str], port: int = 161, timeout: int = 3
) -> dict[str, float]:
    """Mehrere Werte in einer Anfrage; fehlende oder nicht-numerische Werte fehlen im Ergebnis."""
    iterator = getCmd(
        _engine_for(ip_address, port, auth),
        auth.pysnmp_auth(),
        UdpTransportTarget((ip_address, port), timeout=timeout, retries=1),
        ContextData(),
        *[ObjectType(ObjectIdentity(oid)) for oid in oids],
    )
    error_indication, error_status, _error_index, var_binds = next(iterator)

    if error_indication:
        hint = _V3_HINTS.get(type(error_indication).__name__)
        if hint is None and auth.version == "3" and type(error_indication).__name__ == "RequestTimedOut":
            # Kann das Geraet nicht entschluesseln, antwortet es gar nicht
            hint = "Gerät nicht erreichbar oder Privacy-Passwort/Verschlüsselung passt nicht"
        logger.warning(
            "SNMP-Fehler bei %s (v%s): %s%s", ip_address, auth.version, error_indication, f" - {hint}" if hint else ""
        )
        return {}
    if error_status:
        logger.warning("SNMP-Fehlerstatus bei %s: %s", ip_address, error_status.prettyPrint())
        return {}

    results: dict[str, float] = {}
    # Die Antwort enthaelt die Werte in derselben Reihenfolge wie die Anfrage
    for oid, (_name, value) in zip(oids, var_binds):
        try:
            results[oid] = float(value)
        except (ValueError, TypeError):
            pass  # z. B. noSuchInstance, wenn es den Interface-Index nicht gibt
    return results


def poll_interface_counters(ip_address: str, auth: SnmpAuth, if_index: int, port: int = 161) -> dict[str, float]:
    """Status und Byte-Zaehler einer Schnittstelle, alle drei in einer Anfrage."""
    names = {
        f"{OID_IF_OPER_STATUS}.{if_index}": f"if{if_index}_oper_status",
        f"{OID_IF_IN_OCTETS}.{if_index}": f"if{if_index}_in_octets",
        f"{OID_IF_OUT_OCTETS}.{if_index}": f"if{if_index}_out_octets",
    }
    values = snmp_get_many(ip_address, auth, list(names), port)
    return {names[oid]: value for oid, value in values.items()}
