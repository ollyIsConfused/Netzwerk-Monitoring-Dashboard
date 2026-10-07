"""Collector: polls every active device (ping, and SNMP v1/v2c/v3 for switches/routers)
and pushes raw metric samples to the backend API over HTTPS.

Intentionally has NO database access and NO dependency on shared/: it can run
standalone (e.g. on a router/Pi that only needs outbound HTTPS to the backend),
since the backend does all threshold evaluation and alerting server-side
(see backend/app/routers/collector.py -> shared.metrics_engine.record_metric).

Custom agents (NAS/Webserver) push their own metrics directly to the backend's
/agent/push endpoint instead of being polled from here.
"""
import logging
import os
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Optional

import requests

from .ping_client import ping_host
from .snmp_client import poll_interface_counters, snmp_auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("collector")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
COLLECTOR_API_TOKEN = os.environ.get("COLLECTOR_API_TOKEN", "")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "10"))

_AUTH_HEADERS = {"Authorization": f"Bearer {COLLECTOR_API_TOKEN}"}

# In-memory only: the collector is a single long-running process, so a plain
# dict is enough to compute bandwidth deltas between polls. A restart loses at
# most one interval of history, which is fine for this purpose.
_last_raw_counters: dict[tuple[int, str], tuple[float, datetime]] = {}


@dataclass
class CollectorDevice:
    id: int
    name: str
    ip_address: str
    device_type: str
    snmp_enabled: bool
    snmp_community: Optional[str] = field(repr=False)  # nie in Logs/Tracebacks
    snmp_version: str
    snmp_port: int
    snmp_interfaces: Optional[str]
    # SNMP v3 (aeltere Backends liefern diese Felder nicht)
    snmp_v3_user: Optional[str] = None
    snmp_v3_auth_protocol: Optional[str] = None
    snmp_v3_auth_password: Optional[str] = field(default=None, repr=False)
    snmp_v3_priv_protocol: Optional[str] = None
    snmp_v3_priv_password: Optional[str] = field(default=None, repr=False)


_DEVICE_FIELDS = {item.name for item in fields(CollectorDevice)}


def fetch_devices() -> list[CollectorDevice]:
    response = requests.get(f"{BACKEND_URL}/collector/devices", headers=_AUTH_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    # Unbekannte Felder (neuere Backends) ignorieren statt abzustuerzen
    return [CollectorDevice(**{k: v for k, v in item.items() if k in _DEVICE_FIELDS}) for item in response.json()]


def push_metrics(samples: list[dict]) -> None:
    if not samples:
        return
    response = requests.post(
        f"{BACKEND_URL}/collector/metrics",
        json={"samples": samples},
        headers=_AUTH_HEADERS,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def _sample(device_id: int, metric_name: str, value: float, timestamp: datetime) -> dict:
    return {
        "device_id": device_id,
        "metric_name": metric_name,
        "value": value,
        "timestamp": timestamp.isoformat(),
    }


def _poll_ping(device: CollectorDevice, now: datetime) -> list[dict]:
    result = ping_host(device.ip_address)
    samples = [
        _sample(device.id, "reachable", 1.0 if result.reachable else 0.0, now),
        _sample(device.id, "packet_loss_pct", result.packet_loss_pct, now),
    ]
    if result.latency_ms is not None:
        samples.append(_sample(device.id, "latency_ms", result.latency_ms, now))
    return samples


def _record_bandwidth(device: CollectorDevice, raw_metric: str, bps_metric: str, current_value: float, now: datetime) -> Optional[dict]:
    """Derives bits-per-second from two consecutive raw octet-counter samples."""
    cache_key = (device.id, raw_metric)
    previous = _last_raw_counters.get(cache_key)
    _last_raw_counters[cache_key] = (current_value, now)

    if previous is None:
        return None
    prev_value, prev_timestamp = previous
    elapsed = (now - prev_timestamp).total_seconds()
    if elapsed <= 0:
        return None
    delta_octets = current_value - prev_value
    if delta_octets < 0:
        # 32-bit counter wraparound - skip this interval rather than reporting a bogus spike
        return None
    bps = (delta_octets * 8) / elapsed
    return _sample(device.id, bps_metric, bps, now)


def _poll_snmp(device: CollectorDevice, now: datetime) -> list[dict]:
    if not device.snmp_enabled:
        return []
    auth = snmp_auth(
        device.snmp_version,
        device.snmp_community,
        device.snmp_v3_user,
        device.snmp_v3_auth_protocol,
        device.snmp_v3_auth_password,
        device.snmp_v3_priv_protocol,
        device.snmp_v3_priv_password,
    )
    if auth is None:
        return []

    samples: list[dict] = []
    if_indexes = [i.strip() for i in (device.snmp_interfaces or "1").split(",") if i.strip()]

    for if_index_str in if_indexes:
        try:
            if_index = int(if_index_str)
        except ValueError:
            continue

        counters = poll_interface_counters(device.ip_address, auth, if_index, device.snmp_port)
        if not counters:
            continue

        for raw_name, raw_value in counters.items():
            samples.append(_sample(device.id, raw_name, raw_value, now))

        in_key = f"if{if_index}_in_octets"
        out_key = f"if{if_index}_out_octets"
        if in_key in counters:
            bw_sample = _record_bandwidth(device, in_key, f"if{if_index}_in_bps", counters[in_key], now)
            if bw_sample:
                samples.append(bw_sample)
        if out_key in counters:
            bw_sample = _record_bandwidth(device, out_key, f"if{if_index}_out_bps", counters[out_key], now)
            if bw_sample:
                samples.append(bw_sample)

    return samples


def poll_once() -> None:
    try:
        devices = fetch_devices()
    except requests.RequestException:
        logger.exception("Geräteliste konnte nicht vom Backend geladen werden")
        return

    now = datetime.utcnow()
    samples: list[dict] = []
    for device in devices:
        try:
            samples.extend(_poll_ping(device, now))
            if device.device_type in ("switch", "router"):
                samples.extend(_poll_snmp(device, now))
        except Exception:
            logger.exception("Polling für Gerät %s (%s) fehlgeschlagen", device.name, device.ip_address)

    try:
        push_metrics(samples)
    except requests.RequestException:
        logger.exception("Messwerte konnten nicht an das Backend übertragen werden (%d Werte verworfen)", len(samples))


def main() -> None:
    if not COLLECTOR_API_TOKEN:
        logger.warning("COLLECTOR_API_TOKEN ist nicht gesetzt - das Backend wird alle Anfragen ablehnen")
    logger.info("Collector startet, Backend: %s, Poll-Intervall: %ss", BACKEND_URL, POLL_INTERVAL_SECONDS)
    while True:
        start = time.monotonic()
        poll_once()
        elapsed = time.monotonic() - start
        time.sleep(max(0.0, POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
