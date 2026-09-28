from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.models import UserRole, Vlan

from ..deps import get_db
from ..schemas import VlanCreate, VlanOut
from ..security import require_roles

router = APIRouter(prefix="/vlans", tags=["vlans"])


@router.get("", response_model=list[VlanOut])
def list_vlans(db: Session = Depends(get_db)):
    return db.query(Vlan).order_by(Vlan.tag).all()


@router.post("", response_model=VlanOut, dependencies=[Depends(require_roles(UserRole.admin))])
def create_vlan(payload: VlanCreate, db: Session = Depends(get_db)):
    vlan = Vlan(**payload.model_dump())
    db.add(vlan)
    db.commit()
    db.refresh(vlan)
    return vlan
