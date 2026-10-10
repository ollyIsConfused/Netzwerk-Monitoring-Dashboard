"""Bremse gegen Passwort-Raten beim Login.

Zaehlt Fehlversuche im Speicher des Backend-Prozesses (ein uvicorn-Prozess, siehe
deploy/webserver/run-backend.sh) - nach einem Neustart beginnt die Zaehlung von vorn.
"""
import threading
import time
from collections import deque

from fastapi import Request

from .config import LOGIN_BLOCK_SECONDS, LOGIN_MAX_FAILURES

# Ab so vielen Eintraegen werden abgelaufene geloescht, damit der Speicher nicht waechst
_PRUNE_ABOVE = 10_000


class LoginLimiter:
    def __init__(self, max_failures: int, window_seconds: int):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def _limit(self, key: tuple[str, str]) -> int:
        # Ein Benutzername darf von mehreren Adressen aus (z. B. Handy und Laptop) etwas
        # mehr Fehlversuche haben, bevor er gesperrt wird
        return self.max_failures * 2 if key[0] == "user" else self.max_failures

    def _recent(self, key: tuple[str, str], now: float) -> deque[float]:
        attempts = self._failures.get(key, deque())
        while attempts and attempts[0] <= now - self.window_seconds:
            attempts.popleft()
        return attempts

    def retry_after(self, keys: list[tuple[str, str]]) -> int:
        """Sekunden bis zum naechsten erlaubten Versuch, 0 = jetzt erlaubt."""
        now = time.monotonic()
        wait = 0.0
        with self._lock:
            for key in keys:
                attempts = self._recent(key, now)
                if len(attempts) >= self._limit(key):
                    wait = max(wait, attempts[0] + self.window_seconds - now)
        return int(wait) + 1 if wait > 0 else 0

    def record_failure(self, keys: list[tuple[str, str]]) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) > _PRUNE_ABOVE:
                for key in list(self._failures):
                    if not self._recent(key, now):
                        del self._failures[key]
            for key in keys:
                attempts = self._recent(key, now)
                attempts.append(now)
                self._failures[key] = attempts

    def reset(self, keys: list[tuple[str, str]] | None = None) -> None:
        with self._lock:
            if keys is None:
                self._failures.clear()
            for key in keys or []:
                self._failures.pop(key, None)


login_limiter = LoginLimiter(LOGIN_MAX_FAILURES, LOGIN_BLOCK_SECONDS)


def client_ip(request: Request) -> str:
    """Adresse des Besuchers. Der Weg ist Cloudflare -> Caddy -> nginx -> Backend: Cloudflare
    setzt CF-Connecting-IP, im Heimnetz setzt nginx X-Real-IP. Im Heimnetz laesst sich ein
    solcher Header faelschen - deshalb zaehlt zusaetzlich jeder Benutzername fuer sich."""
    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header, "").strip()
        if value:
            return value[:64]
    return request.client.host if request.client else "unbekannt"


def login_keys(request: Request, username: str) -> list[tuple[str, str]]:
    return [("ip", client_ip(request)), ("user", username.strip().lower()[:64])]
