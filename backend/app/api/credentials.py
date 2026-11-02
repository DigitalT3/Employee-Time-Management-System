"""QR credential metadata and lifecycle endpoints (FR-01a, FR-01b, FR-13)."""
import uuid

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.errors import ApiError
from app.models import Employee, QrCredential, User
from app.schemas import CredentialAction, CredentialOut, QrInfoOut
from app.services import audit
from app.services import credentials as svc

router = APIRouter(tags=["credentials"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _employee(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise ApiError(404, "employee_not_found", "Employee not found")
    return employee


def _info(credential: QrCredential) -> dict:
    data = svc.credential_dict(credential)
    base = f"/api/employees/{credential.employee_id}"
    data["png_url"] = f"{base}/qr.png" if data["is_current"] else None
    data["pdf_url"] = f"{base}/qr.pdf" if data["is_current"] else None
    return data


# PUBLIC_INTERFACE
@router.get("/employees/{employee_id}/qr", response_model=QrInfoOut, summary="QR credential metadata",
            description="Returns the current credential's id, status and download links. The token is never returned.")
def qr_info(employee_id: uuid.UUID, db: Session = Depends(get_db),
            _: User = Depends(require_permission("credentials.download"))):
    """Return metadata for the employee's current credential."""
    _employee(db, employee_id)
    return _info(svc.require_current(db, employee_id))


# PUBLIC_INTERFACE
@router.post("/employees/{employee_id}/qr/reprint", response_model=QrInfoOut, summary="Reprint the existing QR",
             description="Records a reprint audit entry and returns the existing credential; never issues a new one.")
def qr_reprint(employee_id: uuid.UUID, db: Session = Depends(get_db),
               user: User = Depends(require_permission("credentials.download"))):
    """Audit a reprint of the unchanged credential (409 when it was revoked)."""
    _employee(db, employee_id)
    credential = svc.require_current(db, employee_id)
    audit.record(db, user.id, "credential.reprint", "employee", employee_id, {"format": "reprint"})
    db.commit()
    return _info(credential)


# PUBLIC_INTERFACE
@router.post("/employees/{employee_id}/qr/reissue", response_model=QrInfoOut, status_code=201,
             summary="Re-issue a QR credential",
             description="Allowed only when the employee has no current credential (after a revoke).")
def qr_reissue(employee_id: uuid.UUID, body: CredentialAction | None = Body(None),
               db: Session = Depends(get_db), user: User = Depends(require_permission("credentials.manage"))):
    """Issue a new credential for an employee whose previous credential was revoked."""
    employee = _employee(db, employee_id)
    return _info(svc.reissue(db, employee, user, body.reason if body else None))


# PUBLIC_INTERFACE
@router.get("/employees/{employee_id}/credentials", response_model=list[CredentialOut],
            summary="Credential history", description="All credentials ever issued to the employee (no tokens).")
def credential_history(employee_id: uuid.UUID, db: Session = Depends(get_db),
                       _: User = Depends(require_permission("credentials.manage"))):
    """Return the preserved credential history, oldest first."""
    _employee(db, employee_id)
    return [svc.credential_dict(c) for c in svc.credential_history(db, employee_id)]


def _lifecycle(fn):
    def endpoint(credential_id: uuid.UUID, body: CredentialAction | None = Body(None),
                 db: Session = Depends(get_db), user: User = Depends(require_permission("credentials.manage"))):
        return svc.credential_dict(fn(db, credential_id, user, body.reason if body else None))
    return endpoint


router.add_api_route("/qr-credentials/{credential_id}/block", _lifecycle(svc.block), methods=["PATCH"],
                     response_model=CredentialOut, summary="Block a credential",
                     description="Active to blocked. Scans are rejected with reason 'blocked'. Audited.")
router.add_api_route("/qr-credentials/{credential_id}/unblock", _lifecycle(svc.unblock), methods=["PATCH"],
                     response_model=CredentialOut, summary="Unblock a credential",
                     description="Blocked to active. Audited.")
router.add_api_route("/qr-credentials/{credential_id}/revoke", _lifecycle(svc.revoke), methods=["PATCH"],
                     response_model=CredentialOut, summary="Revoke a credential",
                     description="Permanent. Scans are rejected with reason 'revoked'; history is preserved. Audited.")
