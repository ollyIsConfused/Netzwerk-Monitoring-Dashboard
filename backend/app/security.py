import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from shared.models import User, UserRole

from .config import COLLECTOR_API_TOKEN, JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from .deps import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Das Frontend erkennt an genau diesem Text, dass es die Seite "Neues Passwort festlegen" zeigen muss
PASSWORD_CHANGE_REQUIRED = "Bitte zuerst ein eigenes Passwort festlegen"

# Ohne leicht verwechselbare Zeichen (l/1, o/0, i), damit man es abtippen kann
_TEMPORARY_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_temporary_password() -> str:
    """Einmal-Passwort im Format xxxx-xxxx-xxxx (ca. 59 Bit Zufall)."""
    return "-".join(
        "".join(secrets.choice(_TEMPORARY_PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3)
    )


def set_user_password(user: User, password: str, *, must_change: bool) -> None:
    """Setzt ein neues Passwort, meldet alle bestehenden Sitzungen ab (Token-Version) und
    erledigt eine offene "Passwort vergessen"-Anfrage. Commit macht der Aufrufer."""
    user.hashed_password = hash_password(password)
    user.must_change_password = must_change
    user.password_reset_requested_at = None
    user.token_version = (user.token_version or 0) + 1


def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": user.username, "role": user.role.value, "ver": user.token_version or 0, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_authenticated_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Gueltige Anmeldung - auch wenn noch ein Passwortwechsel aussteht. Nur fuer die
    Endpunkte, die dafuer gebraucht werden (/auth/me, /auth/change-password)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültige oder abgelaufene Anmeldung",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    # Tokens von vor der letzten Passwortaenderung gelten nicht mehr
    if user is None or not user.is_active or payload.get("ver", 0) != (user.token_version or 0):
        raise credentials_exception
    return user


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED)
    return user


def require_roles(*allowed_roles: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nicht ausreichende Berechtigung für diese Aktion",
            )
        return user

    return dependency


def require_collector_token(authorization: str = Header(default="")) -> None:
    """Auth for the collector service: a single shared secret (no user account),
    since the collector polls on behalf of the whole network, not one user."""
    if not COLLECTOR_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="COLLECTOR_API_TOKEN ist auf dem Backend nicht konfiguriert",
        )
    expected = f"Bearer {COLLECTOR_API_TOKEN}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiges Collector-Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
