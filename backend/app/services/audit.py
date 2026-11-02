"""Append-only audit trail helper."""
import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


# PUBLIC_INTERFACE
def record(db: Session, actor_id: uuid.UUID | None, action: str, entity_type: str, entity_id, details: dict | None = None):
    """Add an audit_log row in the caller's transaction."""
    db.add(AuditLog(actor_user_id=actor_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id), details=details or {}))
