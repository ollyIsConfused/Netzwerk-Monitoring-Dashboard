"""Collector: polls every active device (ping, and SNMP for switches/routers),
stores metric samples and raises/resolves alerts via shared.metrics_engine.

Custom agents (NAS/Webserver) push their own metrics directly to the backend's
/agent/push endpoint instead of being polled from here.
"""
import logging
import os
import time
from datetime import datetime

from shared.database import init_db, session_scope
from shared.metrics_engine import record_metric
from shared.models import AlertLevel, AlertEvent, Device, DeviceType, MetricSample

from .notifier import send_alert_email
from .ping_client import ping_host
from .snmp_client import poll_interface_counters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("collector")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))


def _last_raw_counter(db, device_id: int, metric_name: str) -> tuple[float, datetime] | None:
    sample = (
        db.query(MetricSample)
        .filter(MetricSample.device_id == device_id, MetricSample.metric_name == metric_name)
        .order_by(MetricSample.timestamp.desc())
        .first()
    )
    if sample is None:
        return None
    return sample.value, sample.timestamp


def _poll_ping(db, device: Device) -> None:
    result = ping_host(device.ip_address)
    now = datetime.utcnow()
    record_metric(db, device, "reachable", 1.0 if result.reachable else 0.0, now)
    record_metric(db, device, "packet_loss_pct", result.packet_loss_pct, now)
    if result.latency_ms is not None:
        record_metric(db, device, "latency_ms", result.latency_ms, now)


def _poll_snmp(db, device: Device) -> None:
    if not device.snmp_enabled or not device.snmp_community:
        return

    if_indexes = [i.strip() for i in (device.snmp_interfaces or "1").split(",") if i.strip()]
    now = datetime.utcnow()

    for if_index_str in if_indexes:
        try:
            if_index = int(if_index_str)
        except ValueError:
            continue

        counters = poll_interface_counters(device.ip_address, device.snmp_community, if_index, device.snmp_port)
        if not counters:
            continue

        for raw_name, raw_value in counters.items():
            record_metric(db, device, raw_name, raw_value, now)

        in_key = f"if{if_index}_in_octets"
        out_key = f"if{if_index}_out_octets"
        if in_key in counters:
            _record_bandwidth(db, device, in_key, f"if{if_index}_in_bps", counters[in_key], now)
        if out_key in counters:
            _record_bandwidth(db, device, out_key, f"if{if_index}_out_bps", counters[out_key], now)


def _record_bandwidth(db, device: Device, raw_metric: str, bps_metric: str, current_value: float, now: datetime) -> None:
    """Derives bits-per-second from two consecutive raw octet-counter samples."""
    previous = _last_raw_counter(db, device.id, raw_metric)
    if previous is None:
        return
    prev_value, prev_timestamp = previous
    elapsed = (now - prev_timestamp).total_seconds()
    if elapsed <= 0:
        return
    delta_octets = current_value - prev_value
    if delta_octets < 0:
        # 32-bit counter wraparound - skip this interval rather than reporting a bogus spike
        return
    bps = (delta_octets * 8) / elapsed
    record_metric(db, device, bps_metric, bps, now)


def _dispatch_pending_notifications(db) -> None:
    pending = db.query(AlertEvent).filter(AlertEvent.notified.is_(False)).order_by(AlertEvent.created_at).all()
    for event in pending:
        level_label = {
            AlertLevel.warning: "WARNUNG",
            AlertLevel.critical: "KRITISCH",
            AlertLevel.recovered: "WIEDERHERGESTELLT",
        }[event.level]
        send_alert_email(
            subject=f"[{level_label}] Netzwerk-Monitoring: {event.message}",
            body=f"{event.message}\nZeitpunkt: {event.created_at.isoformat()}",
        )
        event.notified = True
    if pending:
        db.commit()


def poll_once() -> None:
    with session_scope() as db:
        devices = db.query(Device).filter(Device.is_active.is_(True)).all()
        for device in devices:
            try:
                _poll_ping(db, device)
                if device.device_type in (DeviceType.switch, DeviceType.router):
                    _poll_snmp(db, device)
            except Exception:
                logger.exception("Polling für Gerät %s (%s) fehlgeschlagen", device.name, device.ip_address)

        _dispatch_pending_notifications(db)


def main() -> None:
    logger.info("Collector startet, Poll-Intervall: %ss", POLL_INTERVAL_SECONDS)
    init_db()
    while True:
        start = time.monotonic()
        poll_once()
        elapsed = time.monotonic() - start
        time.sleep(max(0.0, POLL_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
