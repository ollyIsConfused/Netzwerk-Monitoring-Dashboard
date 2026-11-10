"""Lesbare Messwerte fuer Alarmtexte und E-Mails: "Port 1 Status = aus" statt
"if49153_oper_status = 2.0". Gegenstueck zu metricInfo/formatMetricValue im Frontend
(frontend/src/api/client.ts) - Aenderungen dort hier nachziehen.
"""
import re
from typing import Optional

_KNOWN = {
    "reachable": ("Erreichbarkeit", ""),
    "latency_ms": ("Antwortzeit", "ms"),
    "packet_loss_pct": ("Paketverlust", "%"),
    "cpu_pct": ("CPU-Last", "%"),
    "disk_pct": ("Festplattenbelegung", "%"),
    "mem_pct": ("Arbeitsspeicher", "%"),
    "temp_c": ("Temperatur", "°C"),
}
_INTERFACE_BPS = re.compile(r"^if(\d+)_(in|out)_bps$")
_INTERFACE_STATUS = re.compile(r"^if(\d+)_oper_status$")
# Weitere Laufwerke vom Agenten, z. B. disk_mnt_storage_pct fuer /mnt/storage
_DISK = re.compile(r"^disk_(.+)_pct$")


def metric_info(metric_name: str, interface_labels: Optional[dict[str, str]] = None) -> tuple[str, str]:
    """(Bezeichnung, Einheit); interface_labels (Device.interface_labels) macht aus
    "Interface 49153" den Portnamen, z. B. "Port 1"."""
    if metric_name in _KNOWN:
        return _KNOWN[metric_name]

    def interface(index: str) -> str:
        return (interface_labels or {}).get(index) or f"Interface {index}"

    match = _INTERFACE_BPS.match(metric_name)
    if match:
        return f"{interface(match[1])} {'eingehend' if match[2] == 'in' else 'ausgehend'}", "bit/s"
    match = _INTERFACE_STATUS.match(metric_name)
    if match:
        return f"{interface(match[1])} Status", ""
    match = _DISK.match(metric_name)
    if match:
        return f"Festplatte /{match[1].replace('_', '/')}", "%"
    return metric_name, ""


def _number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def format_bitrate(bps: float) -> str:
    units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s"]
    index = 0
    while bps >= 1000 and index < len(units) - 1:
        bps /= 1000
        index += 1
    return f"{_number(bps, 0 if bps >= 100 or index == 0 else 1)} {units[index]}"


def format_metric_value(metric_name: str, value: float) -> str:
    if metric_name == "reachable":
        return "erreichbar" if value >= 1 else "nicht erreichbar"
    # SNMP ifOperStatus: 1 = up, 2 = down, alles andere (testing, dormant ...) als Zahl
    if metric_name.endswith("_oper_status") and value in (1, 2):
        return "an" if value == 1 else "aus"
    unit = metric_info(metric_name)[1]
    if unit == "bit/s":
        return format_bitrate(value)
    text = _number(value, 0 if abs(value) >= 100 else 1)
    return f"{text} {unit}" if unit else text
