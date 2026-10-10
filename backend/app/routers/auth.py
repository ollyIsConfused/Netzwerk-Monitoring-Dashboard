import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from shared.models import User

from ..account_mails import admin_recipients, notify_password_reset_request
from ..config import PASSWORD_RESET_COOLDOWN_MINUTES
from ..deps import get_db
from ..login_limiter import client_ip, login_keys, login_limiter
from ..schemas import ForgotPasswordRequest, PasswordChange, Token, UserOut
from ..security import create_access_token, get_authenticated_user, set_user_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

FORGOT_PASSWORD_RESPONSE = (
    "Wenn Benutzername und E-Mail-Adresse zu einem Konto passen, wurde der Administrator benachrichtigt."
)


def _token_response(user: User) -> Token:
    return Token(
        access_token=create_access_token(user),
        role=user.role,
        username=user.username,
        must_change_password=user.must_change_password,
    )


LOGIN_FAILED = "Benutzername oder Passwort falsch"


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    # Lockfeld (Honeypot): im Anmeldeformular unsichtbar. Menschen lassen es leer, einfache
    # Bots fuellen jedes Feld aus - die bekommen dieselbe Antwort wie bei falschem Passwort.
    email: str = Form(default=""),
    db: Session = Depends(get_db),
):
    keys = login_keys(request, form_data.username)
    wait = login_limiter.retry_after(keys)
    if wait:
        logger.warning("Anmeldung gesperrt (zu viele Fehlversuche): Benutzername %r, Adresse %s",
                       form_data.username, client_ip(request))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Fehlversuche. Bitte in {max(1, round(wait / 60))} Minute(n) erneut versuchen.",
            headers={"Retry-After": str(wait)},
        )

    if email:
        logger.warning("Anmeldung abgewiesen: unsichtbares Feld ausgefüllt (vermutlich Bot), Benutzername %r",
                       form_data.username)
        login_limiter.record_failure(keys)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_FAILED)

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        login_limiter.record_failure(keys)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=LOGIN_FAILED)
    # Erfolgreich: Fehlversuche fuer dieses Konto vergessen (die der Adresse bleiben stehen)
    login_limiter.reset([key for key in keys if key[0] == "user"])
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_authenticated_user)):
    return current_user


@router.post("/change-password", response_model=Token)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """Auch waehrend eines ausstehenden Pflicht-Passwortwechsels erlaubt. Meldet alle
    anderen Sitzungen ab und liefert deshalb ein neues Token fuer diese Sitzung."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aktuelles Passwort ist falsch")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Das neue Passwort muss sich vom alten unterscheiden"
        )
    set_user_password(current_user, payload.new_password, must_change=False)
    db.commit()
    return _token_response(current_user)


@router.post("/forgot-password", status_code=202)
def forgot_password(
    payload: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Ohne Anmeldung. Benachrichtigt die Admins, wenn Benutzername und E-Mail zu einem
    aktiven Konto passen. Die Antwort ist immer dieselbe, damit sich nicht ausprobieren
    laesst, welche Konten es gibt."""
    if payload.phone:
        # Lockfeld (Honeypot) ausgefuellt: gleiche Antwort, aber keine Mail
        logger.warning("Passwort vergessen: unsichtbares Feld ausgefüllt (vermutlich Bot) - ignoriert")
        return {"detail": FORGOT_PASSWORD_RESPONSE}

    user = (
        db.query(User)
        .filter(
            func.lower(User.username) == payload.username.strip().lower(),
            func.lower(User.email) == payload.email.lower(),
        )
        .first()
    )
    now = datetime.utcnow()
    cooldown = timedelta(minutes=PASSWORD_RESET_COOLDOWN_MINUTES)

    if user is None or not user.is_active:
        logger.warning("Passwort vergessen: kein aktives Konto zu Benutzername %r und dieser E-Mail", payload.username)
    elif user.password_reset_requested_at and now - user.password_reset_requested_at < cooldown:
        logger.warning("Passwort vergessen: erneute Anfrage für %r innerhalb der Sperrfrist ignoriert", user.username)
    else:
        user.password_reset_requested_at = now
        db.commit()
        # Versand erst nach der Antwort: SMTP kann Sekunden dauern und die Wartezeit wuerde verraten,
        # dass es das Konto gibt
        background_tasks.add_task(
            notify_password_reset_request, admin_recipients(db), user.username, user.email, now
        )
    return {"detail": FORGOT_PASSWORD_RESPONSE}
