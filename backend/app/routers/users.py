from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from shared.models import AlertEvent, User, UserRole

from ..deps import get_db
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_roles

router = APIRouter(prefix="/users", tags=["users"])

require_admin = require_roles(UserRole.admin)


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
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut, dependencies=[Depends(require_admin)])
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
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
        user.hashed_password = hash_password(password)
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


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
