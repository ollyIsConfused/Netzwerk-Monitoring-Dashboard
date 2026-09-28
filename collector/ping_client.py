"""ICMP reachability checks: reachable/unreachable, round-trip time, packet loss."""
import subprocess
from dataclasses import dataclass


@dataclass
class PingResult:
    reachable: bool
    latency_ms: float | None
    packet_loss_pct: float


def ping_host(ip_address: str, count: int = 5, timeout_seconds: int = 2) -> PingResult:
    """Uses the system `ping` binary (present in both the Linux collector container
    and for local testing on macOS/Linux) instead of raw sockets, which would
    require elevated privileges (CAP_NET_RAW) inside the container.
    """
    try:
        proc = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout_seconds), ip_address],
            capture_output=True,
            text=True,
            timeout=count * timeout_seconds + 5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return PingResult(reachable=False, latency_ms=None, packet_loss_pct=100.0)

    output = proc.stdout
    packet_loss_pct = 100.0
    for line in output.splitlines():
        if "packet loss" in line:
            for token in line.split(","):
                token = token.strip()
                if "packet loss" in token:
                    try:
                        packet_loss_pct = float(token.split("%")[0].split()[-1])
                    except (ValueError, IndexError):
                        pass

    avg_latency_ms = None
    for line in output.splitlines():
        # e.g. "rtt min/avg/max/mdev = 0.031/0.041/0.052/0.008 ms"
        if "min/avg/max" in line or "= " in line and "/" in line:
            try:
                stats_part = line.split("=")[1].strip().split()[0]
                avg_latency_ms = float(stats_part.split("/")[1])
            except (IndexError, ValueError):
                pass

    reachable = proc.returncode == 0 and packet_loss_pct < 100.0
    return PingResult(reachable=reachable, latency_ms=avg_latency_ms, packet_loss_pct=packet_loss_pct)
