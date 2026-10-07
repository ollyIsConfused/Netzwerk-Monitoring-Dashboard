from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from shared.models import AlertEvent, Device, DeviceTaggedVlan, MetricSample, ThresholdRule, User, UserRole, Vlan

from ..deps import get_db
from ..device_status import device_state
from ..schemas import (
    DeviceConfigOut,
    DeviceCreate,
    DeviceOut,
    DeviceStatusOut,
    DeviceUpdate,
    ThresholdRuleCreate,
    ThresholdRuleOut,
    ThresholdRuleUpdate,
    VlanAddress,
)
from ..security import get_current_user, require_roles

router = APIRouter(prefix="/devices", tags=["devices"])

require_admin = require_roles(UserRole.admin)

# Spalten ohne NULL in der Datenbank: ein explizites null im PATCH wird ignoriert
_NON_NULLABLE_DEVICE_FIELDS = {
    "name", "ip_address", "device_type", "port_mode", "is_active", "snmp_enabled", "snmp_version", "snmp_port",
    "agent_enabled",
}


def _get_device_or_404(db: Session, device_id: int) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gerät nicht gefunden")
    return device


def _ensure_vlan_exists(db: Session, vlan_id: int | None) -> None:
    if vlan_id is not None and db.query(Vlan).filter(Vlan.id == vlan_id).first() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dieses VLAN existiert nicht")


SNMP_V3_MIN_PASSWORD_LENGTH = 8  # RFC 3414


def _check_snmp(device: Device) -> None:
    """SNMP v3 braucht Benutzer und Anmeldung; Verschluesselung nur mit eigenem Passwort."""
    # Leere Eingaben gelten als "nicht gesetzt"
    for field in ("snmp_v3_user", "snmp_v3_auth_password", "snmp_v3_priv_password"):
        value = getattr(device, field)
        if value is not None and not value.strip():
            setattr(device, field, None)
    if device.snmp_v3_user:
        device.snmp_v3_user = device.snmp_v3_user.strip()
    if not device.snmp_enabled or device.snmp_version != "3":
        return

    def reject(detail: str) -> None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"SNMP v3: {detail}")

    if not device.snmp_v3_user:
        reject("Benutzername fehlt")
    if not device.snmp_v3_auth_protocol or not device.snmp_v3_auth_password:
        reject("Anmeldeverfahren und Auth-Passwort angeben")
    if len(device.snmp_v3_auth_password) < SNMP_V3_MIN_PASSWORD_LENGTH:
        reject(f"Das Auth-Passwort braucht mindestens {SNMP_V3_MIN_PASSWORD_LENGTH} Zeichen")
    if device.snmp_v3_priv_protocol and len(device.snmp_v3_priv_password or "") < SNMP_V3_MIN_PASSWORD_LENGTH:
        reject(f"Das Privacy-Passwort braucht mindestens {SNMP_V3_MIN_PASSWORD_LENGTH} Zeichen")


def _set_tagged_vlans(
    db: Session, device: Device, vlan_ids: list[int], addresses: list[VlanAddress] | None
) -> None:
    """Getaggte VLANs eines Trunk-Ports pruefen und samt Adressen setzen. Ein Access-Port hat keine.
    addresses=None behaelt die Adressen der VLANs, die getaggt bleiben."""
    if device.port_mode != "trunk":
        device.tagged_vlan_links = []
        return
    vlan_ids = list(dict.fromkeys(vlan_ids))
    if not vlan_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Ein Trunk-Port braucht mindestens ein getaggtes VLAN"
        )
    if device.vlan_id in vlan_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Das native VLAN ist ungetaggt und kann nicht zusätzlich getaggt sein",
        )
    if db.query(Vlan).filter(Vlan.id.in_(vlan_ids)).count() != len(vlan_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mindestens ein getaggtes VLAN existiert nicht")

    existing = {link.vlan_id: link for link in device.tagged_vlan_links}
    if addresses is None:
        address_by_vlan = {vlan_id: link.ip_address for vlan_id, link in existing.items() if vlan_id in vlan_ids}
    else:
        address_by_vlan = {}
        for entry in addresses:
            if entry.vlan_id in address_by_vlan:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pro VLAN nur eine Adresse")
            if entry.vlan_id not in vlan_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Eine Adresse gehört zu einem VLAN, das an diesem Port nicht getaggt ist",
                )
            address_by_vlan[entry.vlan_id] = entry.ip_address

    # Bestehende Zuordnungen weiterverwenden statt sie zu loeschen und neu anzulegen
    links = []
    for vlan_id in vlan_ids:
        link = existing.get(vlan_id) or DeviceTaggedVlan(vlan_id=vlan_id)
        link.ip_address = address_by_vlan.get(vlan_id)
        links.append(link)
    device.tagged_vlan_links = links


_DEVICE_RELATIONS = (selectinload(Device.tagged_vlans), selectinload(Device.tagged_vlan_links))


@router.get("", response_model=list[DeviceOut])
def list_devices(vlan_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    query = db.query(Device).options(*_DEVICE_RELATIONS)
    if vlan_id is not None:
        # Auch Trunk-Geraete, die das VLAN getaggt fuehren
        query = query.filter(or_(Device.vlan_id == vlan_id, Device.tagged_vlans.any(Vlan.id == vlan_id)))
    return query.order_by(Device.name).all()


@router.get("/status", response_model=list[DeviceStatusOut])
def list_device_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Latest known value per metric, per device, plus an aggregated overall status."""
    devices = db.query(Device).options(*_DEVICE_RELATIONS).filter(Device.is_active.is_(True)).all()
    now = datetime.utcnow()
    results: list[DeviceStatusOut] = []
    for device in devices:
        state = device_state(db, device, now)
        results.append(DeviceStatusOut(device=DeviceOut.model_validate(device), **vars(state)))
    return results


@router.post("", response_model=DeviceOut, status_code=201, dependencies=[Depends(require_admin)])
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    _ensure_vlan_exists(db, payload.vlan_id)
    device = Device(**payload.model_dump(exclude={"tagged_vlan_ids", "vlan_addresses"}))
    _set_tagged_vlans(db, device, payload.tagged_vlan_ids, payload.vlan_addresses)
    _check_snmp(device)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _get_device_or_404(db, device_id)


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
def get_device_status(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    device = _get_device_or_404(db, device_id)
    return DeviceStatusOut(device=DeviceOut.model_validate(device), **vars(device_state(db, device)))


@router.get("/{device_id}/config", response_model=DeviceConfigOut, dependencies=[Depends(require_admin)])
def get_device_config(device_id: int, db: Session = Depends(get_db)):
    """Vollstaendige Konfiguration (inkl. SNMP-Community/Agent-Token) fuer das Bearbeiten-Formular."""
    return _get_device_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceOut, dependencies=[Depends(require_admin)])
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    device = _get_device_or_404(db, device_id)
    changes = payload.model_dump(exclude_unset=True, exclude={"vlan_addresses"})
    tagged_vlan_ids = changes.pop("tagged_vlan_ids", None)
    if "vlan_id" in changes:
        _ensure_vlan_exists(db, changes["vlan_id"])
    for field, value in changes.items():
        if value is None and field in _NON_NULLABLE_DEVICE_FIELDS:
            continue
        setattr(device, field, value)
    # Anschluss, natives VLAN, getaggte VLANs oder Adressen geaendert: Zuordnung neu pruefen
    if (
        tagged_vlan_ids is not None
        or payload.vlan_addresses is not None
        or "port_mode" in changes
        or "vlan_id" in changes
    ):
        ids = tagged_vlan_ids if tagged_vlan_ids is not None else [link.vlan_id for link in device.tagged_vlan_links]
        _set_tagged_vlans(db, device, ids, payload.vlan_addresses)
    _check_snmp(device)
    db.commit()
    db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = _get_device_or_404(db, device_id)
    # Messwerte und Alarme verweisen per Fremdschluessel auf das Geraet und muessen
    # zuerst weg, sonst lehnt PostgreSQL das Loeschen ab.
    db.query(MetricSample).filter(MetricSample.device_id == device.id).delete(synchronize_session=False)
    db.query(AlertEvent).filter(AlertEvent.device_id == device.id).delete(synchronize_session=False)
    db.delete(device)
    db.commit()


@router.get("/{device_id}/thresholds", response_model=list[ThresholdRuleOut])
def list_thresholds(device_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return (
        db.query(ThresholdRule)
        .filter(ThresholdRule.device_id == device_id)
        .order_by(ThresholdRule.metric_name)
        .all()
    )


@router.post(
    "/{device_id}/thresholds",
    response_model=ThresholdRuleOut,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_threshold(device_id: int, payload: ThresholdRuleCreate, db: Session = Depends(get_db)):
    _get_device_or_404(db, device_id)
    existing = (
        db.query(ThresholdRule)
        .filter(ThresholdRule.device_id == device_id, ThresholdRule.metric_name == payload.metric_name)
        .first()
    )
    if existing:
        # Pro Geraet und Metrik darf es nur eine Regel geben, sonst waere die Auswertung mehrdeutig
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Für {payload.metric_name} gibt es schon einen Schwellenwert - bitte bearbeiten",
        )
    rule = ThresholdRule(device_id=device_id, **payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _get_rule_or_404(db: Session, device_id: int, rule_id: int) -> ThresholdRule:
    rule = (
        db.query(ThresholdRule)
        .filter(ThresholdRule.id == rule_id, ThresholdRule.device_id == device_id)
        .first()
    )
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schwellenwert nicht gefunden")
    return rule


@router.patch(
    "/{device_id}/thresholds/{rule_id}",
    response_model=ThresholdRuleOut,
    dependencies=[Depends(require_admin)],
)
def update_threshold(device_id: int, rule_id: int, payload: ThresholdRuleUpdate, db: Session = Depends(get_db)):
    rule = _get_rule_or_404(db, device_id, rule_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "consecutive_breaches_required" and value is None:
            continue
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{device_id}/thresholds/{rule_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_threshold(device_id: int, rule_id: int, db: Session = Depends(get_db)):
    rule = _get_rule_or_404(db, device_id, rule_id)
    db.delete(rule)
    db.commit()
