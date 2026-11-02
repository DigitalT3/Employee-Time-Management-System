"""Permanent QR credential lifecycle and repeatable QR PNG/PDF rendering (DEC-02)."""
import io
import uuid
from datetime import datetime

import qrcode
from reportlab.lib.pagesizes import A6
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.crypto import decrypt_token, encrypt_token, new_token, token_hash
from app.errors import ApiError
from app.models import Employee, QrCredential, User
from app.services import audit

PAYLOAD_PREFIX = "ETMS:"
CURRENT_STATUSES = ("active", "blocked")


# PUBLIC_INTERFACE
def issue_credential(db: Session, employee: Employee) -> QrCredential:
    """Create one permanent QR credential in the caller's transaction."""
    token = new_token()
    credential = QrCredential(
        id=uuid.uuid4(),
        employee_id=employee.id,
        token_hash=token_hash(token),
        token_encrypted=encrypt_token(token),
    )
    db.add(credential)
    return credential


# PUBLIC_INTERFACE
def current_credential(db: Session, employee_id: uuid.UUID) -> QrCredential | None:
    """Return the employee's current (active or blocked) credential, or None."""
    return db.scalar(
        select(QrCredential).where(
            QrCredential.employee_id == employee_id, QrCredential.status.in_(CURRENT_STATUSES)
        )
    )


# PUBLIC_INTERFACE
def credential_history(db: Session, employee_id: uuid.UUID) -> list[QrCredential]:
    """Return every credential ever issued to the employee, oldest first."""
    return list(
        db.scalars(
            select(QrCredential)
            .where(QrCredential.employee_id == employee_id)
            .order_by(QrCredential.issued_at, QrCredential.id)
        )
    )


# PUBLIC_INTERFACE
def display_status(db: Session, employee_id: uuid.UUID) -> tuple[uuid.UUID | None, str | None]:
    """Return (current credential id, status to display); a revoked-only employee shows 'revoked'."""
    current = current_credential(db, employee_id)
    if current:
        return current.id, current.status
    latest = db.scalar(
        select(QrCredential.status)
        .where(QrCredential.employee_id == employee_id)
        .order_by(QrCredential.issued_at.desc())
        .limit(1)
    )
    return None, latest


# PUBLIC_INTERFACE
def credential_dict(credential: QrCredential) -> dict:
    """Serialise credential metadata. The token and its hash are never included."""
    return {
        "id": str(credential.id),
        "employee_id": str(credential.employee_id),
        "status": credential.status,
        "is_current": credential.status in CURRENT_STATUSES,
        "issued_at": credential.issued_at.isoformat(),
        "blocked_at": credential.blocked_at.isoformat() if credential.blocked_at else None,
        "revoked_at": credential.revoked_at.isoformat() if credential.revoked_at else None,
    }


def _locked(db: Session, credential_id: uuid.UUID) -> QrCredential:
    credential = db.scalar(
        select(QrCredential).where(QrCredential.id == credential_id).with_for_update()
    )
    if credential is None:
        raise ApiError(404, "credential_not_found", "Credential not found")
    return credential


def _transition(
    db: Session, credential_id: uuid.UUID, allowed_from: tuple[str, ...], to: str,
    action: str, actor: User, reason: str | None,
) -> QrCredential:
    credential = _locked(db, credential_id)
    if credential.status not in allowed_from:
        raise ApiError(
            409, "invalid_credential_state",
            f"A {credential.status} credential cannot be changed to {to}",
        )
    previous = credential.status
    now: datetime = clock.now()
    credential.status = to
    if to == "blocked":
        credential.blocked_at = now
    elif to == "active":
        credential.blocked_at = None
    elif to == "revoked":
        credential.revoked_at = now
    audit.record(db, actor.id, action, "credential", credential.id,
                 {"employee_id": str(credential.employee_id), "from": previous, "to": to,
                  "reason": (reason or "").strip() or None})
    db.commit()
    db.refresh(credential)
    return credential


# PUBLIC_INTERFACE
def block(db: Session, credential_id: uuid.UUID, actor: User, reason: str | None = None) -> QrCredential:
    """Block an active credential: scans are rejected until it is unblocked."""
    return _transition(db, credential_id, ("active",), "blocked", "credential.block", actor, reason)


# PUBLIC_INTERFACE
def unblock(db: Session, credential_id: uuid.UUID, actor: User, reason: str | None = None) -> QrCredential:
    """Restore a blocked credential to active."""
    return _transition(db, credential_id, ("blocked",), "active", "credential.unblock", actor, reason)


# PUBLIC_INTERFACE
def revoke(db: Session, credential_id: uuid.UUID, actor: User, reason: str | None = None) -> QrCredential:
    """Permanently revoke an active or blocked credential. The row is kept as history."""
    return _transition(db, credential_id, ("active", "blocked"), "revoked", "credential.revoke", actor, reason)


# PUBLIC_INTERFACE
def reissue(db: Session, employee: Employee, actor: User, reason: str | None = None) -> QrCredential:
    """Issue a new credential, allowed only when the employee has no current credential."""
    # Serialise concurrent re-issues for one employee on the employee row.
    db.scalar(select(Employee.id).where(Employee.id == employee.id).with_for_update())
    if current_credential(db, employee.id) is not None:
        raise ApiError(409, "credential_exists", "The employee already has a current credential; revoke it first")
    credential = issue_credential(db, employee)
    db.flush()
    audit.record(db, actor.id, "credential.reissue", "credential", credential.id,
                 {"employee_id": str(employee.id), "reason": (reason or "").strip() or None})
    db.commit()
    db.refresh(credential)
    return credential


# PUBLIC_INTERFACE
def require_current(db: Session, employee_id: uuid.UUID) -> QrCredential:
    """Return the current credential or raise 409 credential_revoked / 404 credential_not_found."""
    credential = current_credential(db, employee_id)
    if credential is not None:
        return credential
    if credential_history(db, employee_id):
        raise ApiError(409, "credential_revoked", "The employee's credential was revoked; re-issue a new one")
    raise ApiError(404, "credential_not_found", "Employee has no credential")


# PUBLIC_INTERFACE
def normalize_payload(payload: str) -> str:
    """Normalize a scanned QR payload and accept the optional ETMS prefix."""
    cleaned = payload.strip()
    return cleaned[len(PAYLOAD_PREFIX):] if cleaned.startswith(PAYLOAD_PREFIX) else cleaned


# PUBLIC_INTERFACE
def credential_payload(credential: QrCredential) -> str:
    """Decrypt and return the employee's unchanged permanent QR payload."""
    return decrypt_token(credential.token_encrypted)


# PUBLIC_INTERFACE
def render_png(payload: str) -> bytes:
    """Render deterministic PNG bytes for a QR payload."""
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    code.add_data(payload)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
    return buffer.getvalue()


# PUBLIC_INTERFACE
def render_pdf(payload: str, employee: Employee) -> bytes:
    """Render a printable A6 PDF badge containing the employee QR code."""
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=A6, invariant=1)
    width, height = A6
    image_size = 200
    document.drawImage(
        ImageReader(io.BytesIO(render_png(payload))),
        (width - image_size) / 2,
        height - image_size - 40,
        image_size,
        image_size,
    )
    document.setFont("Helvetica-Bold", 14)
    document.drawCentredString(
        width / 2,
        height - image_size - 65,
        f"{employee.first_name} {employee.last_name}",
    )
    document.setFont("Helvetica", 11)
    document.drawCentredString(width / 2, height - image_size - 82, employee.employee_number)
    document.showPage()
    document.save()
    return buffer.getvalue()
