"""Anzeigenamen fuer SNMP-Schnittstellen: "Port 1" statt "Interface 49153".

Der Collector meldet je Interface-Index den Namen, den das Geraet selbst nennt (ifName,
z. B. "gigabitEthernet 1/0/1" beim TP-Link oder "eth0.20" beim Router-Pi). Daraus wird hier
ein kurzer Anzeigename. Von Hand vergebene Namen im Geraetedialog haben Vorrang.
"""
import json
import re
from typing import Optional

# Switch-Ports im Format Einheit/Steckplatz/Port, z. B. "gigabitEthernet 1/0/1" oder "Gi1/0/24"
_UNIT_SLOT_PORT = re.compile(r"(\d+)/(\d+)/(\d+)\s*$")

MAX_LABEL_LENGTH = 40
MAX_DETECTED_NAME_LENGTH = 128


def friendly_interface_name(name: str) -> str:
    """"gigabitEthernet 1/0/1" -> "Port 1", bei gestapelten Switches "Port 2/1". Andere
    Namen (eth0.20, wg0, Vlan-interface1) bleiben wie sie sind."""
    name = name.strip()
    match = _UNIT_SLOT_PORT.search(name)
    if match:
        unit, _slot, port = match.groups()
        return f"Port {port}" if unit == "1" else f"Port {unit}/{port}"
    return name


def load_name_map(raw: Optional[str]) -> dict[str, str]:
    """JSON {"49153": "..."} aus der Datenbank; Unbrauchbares wird ignoriert."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if str(key).isdigit() and value}


def dump_name_map(names: Optional[dict[str, str]]) -> Optional[str]:
    cleaned = {str(key): value for key, value in (names or {}).items() if value}
    if not cleaned:
        return None
    return json.dumps(dict(sorted(cleaned.items(), key=lambda item: int(item[0]))), ensure_ascii=False)
