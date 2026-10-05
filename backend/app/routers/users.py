import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from shared.models import AlertEvent, User, UserRole

from ..account_mails import send_temporary_password
from ..deps import get_db
from ..schemas import TemporaryPasswordResult, UserCreate, UserOut, UserUpdate
from ..security import generate_temporary_password, hash_password, require_roles, set_user_password

router = APIRouter(prefix="/users", tags=["users"])

require_admin = require_roles(UserRole.admin)

OWN_PASSWORD_HINT = "Das eigene Passwort bitte unter „Mein Konto“ ändern"


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    return user


def _ensure_another_active_admin(db: Session, user: User) -> None:
    """Verhindert, dass sich das System aussperrt: der letzte aktive Admin darf weder
    herabgestuft, deaktiviert noch geloescht werden."""
    other_admins = (
        db.query(User)
        .filter(User.role == UserRole.admin, User.is_active.is_(True), User.id != user.id)
        .count()
    )
    if other_admins == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mindestens ein aktiver Admin muss erhalten bleiben",
        )


@router.get("", response_model=list[UserOut], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.username).all()


@router.post("", response_model=UserOut, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Benutzername ist bereits vergeben")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-Mail-Adresse ist bereits vergeben")

    user = User(
        username=payload.username,
        email=payload.email,
        # Ohne Passwort: zufaelliges, niemandem bekanntes Passwort, bis der Admin ein Einmal-Passwort schickt
        hashed_password=hash_password(payload.password or secrets.token_urlsafe(32)),
        role=payload.role,
        # Das Startpasswort kennt der Admin - der Benutzer legt beim ersten Anmelden ein eigenes fest
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, payload: UserUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)
):
    user = _get_user_or_404(db, user_id)
    changes = payload.model_dump(exclude_unset=True)

    new_role = changes.get("role")
    loses_admin = user.role == UserRole.admin and user.is_active and (
        (new_role is not None and new_role != UserRole.admin) or changes.get("is_active") is False
    )
    if loses_admin:
        _ensure_another_active_admin(db, user)

    if "email" in changes and changes["email"] != user.email:
        if db.query(User).filter(User.email == changes["email"], User.id != user.id).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="E-Mail-Adresse ist bereits vergeben")

    password = changes.pop("password", None)
    if password:
        # Eigenes Passwort nur mit dem aktuellen Passwort (Mein Konto) - sonst wuerde sich der Admin selbst abmelden
        if user.id == current_user.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=OWN_PASSWORD_HINT)
        set_user_password(user, password, must_change=True)
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/temporary-password", response_model=TemporaryPasswordResult)
def send_temporary_password_to_user(
    user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)
):
    """Erzeugt ein Einmal-Passwort und schickt es an die hinterlegte E-Mail-Adresse des
    Benutzers. Klappt der Versand nicht, kommt das Passwort einmalig in der Antwort zurueck."""
    user = _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=OWN_PASSWORD_HINT)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Das Konto ist gesperrt - zuerst wieder aktivieren"
        )

    password = generate_temporary_password()
    set_user_password(user, password, must_change=True)
    db.commit()

    sent = send_temporary_password(user, password)
    return TemporaryPasswordResult(email=user.email, email_sent=sent, temporary_password=None if sent else password)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    user = _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Das eigene Konto kann nicht gelöscht werden")
    if user.role == UserRole.admin and user.is_active:
        _ensure_another_active_admin(db, user)

    # Quittierte Alarme bleiben erhalten, verlieren aber den Verweis auf den Benutzer
    db.query(AlertEvent).filter(AlertEvent.acknowledged_by_id == user.id).update(
        {AlertEvent.acknowledged_by_id: None}, synchronize_session=False
    )
    db.delete(user)
    db.commit()
