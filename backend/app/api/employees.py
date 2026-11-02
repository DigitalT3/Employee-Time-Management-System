"""Employee management and permanent QR credential downloads (FR-01, FR-01a/b)."""
import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.errors import ApiError
from app.models import Employee, EmployeeSite, Site, User
from app.schemas import EmployeeCreate, EmployeeOut, EmployeeStatusIn, EmployeeUpdate, SiteRef
from app.services import audit
from app.services.credentials import (
    credential_payload, display_status, issue_credential, render_pdf, render_png, require_current,
)

router = APIRouter(prefix="/employees", tags=["employees"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _out(db: Session, e: Employee) -> EmployeeOut:
    sites = db.execute(
        select(Site.id, Site.code, Site.name)
        .join(EmployeeSite, EmployeeSite.site_id == Site.id)
        .where(EmployeeSite.employee_id == e.id)
        .order_by(Site.code)
    ).all()
    credential_id, status = display_status(db, e.id)
    return EmployeeOut(id=e.id, employee_number=e.employee_number, first_name=e.first_name, last_name=e.last_name,
                       is_active=e.is_active, site_ids=[s.id for s in sites],
                       sites=[SiteRef(id=s.id, code=s.code, name=s.name) for s in sites],
                       credential_id=credential_id, credential_status=status,
                       created_at=e.created_at, updated_at=e.updated_at)


def _load(db: Session, employee_id: uuid.UUID) -> Employee:
    e = db.get(Employee, employee_id)
    if not e:
        raise ApiError(404, "employee_not_found", "Employee not found")
    return e


def _check_sites(db: Session, site_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    ids = list(dict.fromkeys(site_ids))
    found = db.scalar(select(func.count()).select_from(Site).where(Site.id.in_(ids)))
    if found != len(ids):
        raise ApiError(422, "unknown_site", "One or more site ids do not exist")
    return ids


def _number_taken(db: Session, number: str, exclude: uuid.UUID | None = None) -> bool:
    q = select(Employee.id).where(Employee.employee_number == number)
    if exclude:
        q = q.where(Employee.id != exclude)
    return db.scalar(q) is not None


# PUBLIC_INTERFACE
@router.get("", response_model=list[EmployeeOut], summary="List employees",
            description="Filter by free-text search (number/name), active flag and site.")
def list_employees(search: str | None = Query(None, max_length=100), active: bool | None = None,
                   site_id: uuid.UUID | None = None, db: Session = Depends(get_db),
                   _: User = Depends(require_permission("employees.view"))):
    """List employees ordered by employee number."""
    q = select(Employee).order_by(Employee.employee_number)
    if search:
        like = f"%{search.strip()}%"
        q = q.where(or_(Employee.employee_number.ilike(like), Employee.first_name.ilike(like),
                        Employee.last_name.ilike(like)))
    if active is not None:
        q = q.where(Employee.is_active == active)
    if site_id:
        q = q.where(Employee.id.in_(select(EmployeeSite.employee_id).where(EmployeeSite.site_id == site_id)))
    return [_out(db, e) for e in db.scalars(q)]


# PUBLIC_INTERFACE
@router.post("", response_model=EmployeeOut, status_code=201, summary="Create employee",
             description="Atomically creates the employee, site assignments and a unique permanent QR credential.")
def create_employee(body: EmployeeCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("employees.manage"))):
    """Create an employee with a permanent QR credential in one transaction."""
    site_ids = _check_sites(db, body.site_ids)
    if _number_taken(db, body.employee_number):
        raise ApiError(409, "employee_number_taken", "Employee number already exists")
    e = Employee(id=uuid.uuid4(), employee_number=body.employee_number, first_name=body.first_name,
                 last_name=body.last_name)
    db.add(e)
    db.flush()
    for sid in site_ids:
        db.add(EmployeeSite(employee_id=e.id, site_id=sid))
    issue_credential(db, e)
    audit.record(db, user.id, "employee.create", "employee", e.id, {"employee_number": e.employee_number})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "employee_number_taken", "Employee number already exists")
    db.refresh(e)
    return _out(db, e)


# PUBLIC_INTERFACE
@router.get("/{employee_id}", response_model=EmployeeOut, summary="Get employee")
def get_employee(employee_id: uuid.UUID, db: Session = Depends(get_db),
                 _: User = Depends(require_permission("employees.view"))):
    """Return one employee."""
    return _out(db, _load(db, employee_id))


# PUBLIC_INTERFACE
@router.put("/{employee_id}", response_model=EmployeeOut, summary="Update employee (alias of PATCH)",
            description="Specification-named alias of PATCH; only supplied fields change. The QR credential is unchanged.")
@router.patch("/{employee_id}", response_model=EmployeeOut, summary="Update employee",
              description="Updates name/number and optionally replaces site assignments. The QR credential is unchanged.")
def update_employee(employee_id: uuid.UUID, body: EmployeeUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("employees.manage"))):
    """Partially update an employee."""
    e = _load(db, employee_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "employee_number" in changes:
        changes["employee_number"] = changes["employee_number"].strip()
        if _number_taken(db, changes["employee_number"], exclude=e.id):
            raise ApiError(409, "employee_number_taken", "Employee number already exists")
    site_ids = changes.pop("site_ids", None)
    for k, v in changes.items():
        setattr(e, k, v.strip() if isinstance(v, str) else v)
    if site_ids is not None:
        ids = _check_sites(db, site_ids)
        db.query(EmployeeSite).filter(EmployeeSite.employee_id == e.id).delete()
        for sid in ids:
            db.add(EmployeeSite(employee_id=e.id, site_id=sid))
        changes["site_ids"] = [str(s) for s in ids]
    audit.record(db, user.id, "employee.update", "employee", e.id, {"fields": sorted(changes)})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "employee_number_taken", "Employee number already exists")
    db.refresh(e)
    return _out(db, e)


def _set_active(db: Session, employee_id: uuid.UUID, active: bool, user: User) -> EmployeeOut:
    e = _load(db, employee_id)
    e.is_active = active
    audit.record(db, user.id, "employee.activate" if active else "employee.deactivate", "employee", e.id)
    db.commit()
    db.refresh(e)
    return _out(db, e)


# PUBLIC_INTERFACE
@router.patch("/{employee_id}/status", response_model=EmployeeOut, summary="Set employee status",
              description="Activate or deactivate an employee with {\"is_active\": bool}.")
def set_employee_status(employee_id: uuid.UUID, body: EmployeeStatusIn, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("employees.manage"))):
    """Set the employee's active flag (history and credential are preserved)."""
    return _set_active(db, employee_id, body.is_active, user)


# PUBLIC_INTERFACE
@router.post("/{employee_id}/activate", response_model=EmployeeOut, summary="Activate employee")
def activate_employee(employee_id: uuid.UUID, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("employees.manage"))):
    """Mark an employee active (scans accepted again)."""
    return _set_active(db, employee_id, True, user)


# PUBLIC_INTERFACE
@router.post("/{employee_id}/deactivate", response_model=EmployeeOut, summary="Deactivate employee",
             description="Scans by a deactivated employee are rejected; history and credential are preserved.")
def deactivate_employee(employee_id: uuid.UUID, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("employees.manage"))):
    """Mark an employee inactive."""
    return _set_active(db, employee_id, False, user)


# PUBLIC_INTERFACE
@router.get("/{employee_id}/qr.png", summary="Download QR PNG", response_class=Response,
            responses={200: {"content": {"image/png": {}}}, 409: {"description": "Credential revoked"}})
def qr_png(employee_id: uuid.UUID, db: Session = Depends(get_db),
           user: User = Depends(require_permission("credentials.download"))):
    """Return the permanent QR code as PNG (reprint never rotates the credential)."""
    e = _load(db, employee_id)
    data = render_png(credential_payload(require_current(db, e.id)))
    audit.record(db, user.id, "credential.reprint", "employee", e.id, {"format": "png"})
    db.commit()
    headers = {**NO_STORE, "Content-Disposition": f'attachment; filename="qr-{e.employee_number}.png"'}
    return Response(content=data, media_type="image/png", headers=headers)


# PUBLIC_INTERFACE
@router.get("/{employee_id}/qr.pdf", summary="Download printable QR badge PDF", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}, 409: {"description": "Credential revoked"}})
def qr_pdf(employee_id: uuid.UUID, db: Session = Depends(get_db),
           user: User = Depends(require_permission("credentials.download"))):
    """Return a printable A6 badge PDF containing the permanent QR code."""
    e = _load(db, employee_id)
    data = render_pdf(credential_payload(require_current(db, e.id)), e)
    audit.record(db, user.id, "credential.reprint", "employee", e.id, {"format": "pdf"})
    db.commit()
    headers = {**NO_STORE, "Content-Disposition": f'attachment; filename="qr-{e.employee_number}.pdf"'}
    return Response(content=data, media_type="application/pdf", headers=headers)
