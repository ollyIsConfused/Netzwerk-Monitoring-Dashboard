from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from shared.models import Device, User, UserRole, Vlan

from ..deps import get_db
from ..schemas import VlanCreate, VlanOut, VlanUpdate
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/vlans", tags=["vlans"])

require_admin = require_roles(UserRole.admin)


def _ensure_tag_free(db: Session, tag: int, exclude_id: int | None = None) -> None:
    query = db.query(Vlan).filter(Vlan.tag == tag)
    if exclude_id is not None:
        query = query.filter(Vlan.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"VLAN-Tag {tag} ist bereits vergeben")


@router.get("", response_model=list[VlanOut])
def list_vlans(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Vlan).order_by(Vlan.tag).all()


@router.post("", response_model=VlanOut, status_code=201, dependencies=[Depends(require_admin)])
def create_vlan(payload: VlanCreate, db: Session = Depends(get_db)):
    _ensure_tag_free(db, payload.tag)
    vlan = Vlan(**payload.model_dump())
    db.add(vlan)
    db.commit()
    db.refresh(vlan)
    return vlan


@router.patch("/{vlan_id}", response_model=VlanOut, dependencies=[Depends(require_admin)])
def update_vlan(vlan_id: int, payload: VlanUpdate, db: Session = Depends(get_db)):
    vlan = db.query(Vlan).filter(Vlan.id == vlan_id).first()
    if vlan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN nicht gefunden")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("tag") is not None:
        _ensure_tag_free(db, changes["tag"], exclude_id=vlan.id)
    for field, value in changes.items():
        if field in ("name", "tag") and value is None:
            continue
        setattr(vlan, field, value)
    db.commit()
    db.refresh(vlan)
    return vlan


@router.delete("/{vlan_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_vlan(vlan_id: int, db: Session = Depends(get_db)):
    vlan = db.query(Vlan).filter(Vlan.id == vlan_id).first()
    if vlan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VLAN nicht gefunden")
    # Geraete bleiben erhalten und werden nur keinem VLAN mehr zugeordnet
    db.query(Device).filter(Device.vlan_id == vlan.id).update({Device.vlan_id: None}, synchronize_session=False)
    db.delete(vlan)
    db.commit()
