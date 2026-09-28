"""Minimal synchronous SNMP GET client (SNMPv1/v2c) built on pysnmp's classic hlapi.

Only what the collector needs: sysUpTime and per-interface counters
(ifOperStatus, ifInOctets, ifOutOctets) for switches/routers.
"""
import logging

from pysnmp.hlapi import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    getCmd,
)

logger = logging.getLogger(__name__)

OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"
OID_IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"


def snmp_get(ip_address: str, community: str, oid: str, port: int = 161, timeout: int = 3) -> float | None:
    iterator = getCmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),  # mpModel=1 -> SNMPv2c
        UdpTransportTarget((ip_address, port), timeout=timeout, retries=1),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    error_indication, error_status, _error_index, var_binds = next(iterator)

    if error_indication:
        logger.warning("SNMP-Fehler bei %s (%s): %s", ip_address, oid, error_indication)
        return None
    if error_status:
        logger.warning("SNMP-Fehlerstatus bei %s (%s): %s", ip_address, oid, error_status.prettyPrint())
        return None

    for _name, value in var_binds:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    return None


def poll_interface_counters(
    ip_address: str, community: str, if_index: int, port: int = 161
) -> dict[str, float]:
    """Returns raw counters for one interface: oper status, in/out octets."""
    results: dict[str, float] = {}

    oper_status = snmp_get(ip_address, community, f"{OID_IF_OPER_STATUS}.{if_index}", port)
    if oper_status is not None:
        results[f"if{if_index}_oper_status"] = oper_status

    in_octets = snmp_get(ip_address, community, f"{OID_IF_IN_OCTETS}.{if_index}", port)
    if in_octets is not None:
        results[f"if{if_index}_in_octets"] = in_octets

    out_octets = snmp_get(ip_address, community, f"{OID_IF_OUT_OCTETS}.{if_index}", port)
    if out_octets is not None:
        results[f"if{if_index}_out_octets"] = out_octets

    return results


def poll_sys_uptime(ip_address: str, community: str, port: int = 161) -> float | None:
    return snmp_get(ip_address, community, OID_SYS_UPTIME, port)
