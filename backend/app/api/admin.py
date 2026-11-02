"""Administrator endpoints: configurable permission matrix (DEC-10)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import permissions as perms
from app.api.deps import get_db, require_permission
from app.errors import ApiError
from app.models import RolePermission, User
from app.schemas import PermissionMatrixIn, PermissionMatrixOut
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])


def _view(db: Session) -> dict:
    return {
        "roles": list(perms.ROLES),
        "permissions": [{"key": k, "description": d} for k, d in perms.PERMISSIONS.items()],
        "matrix": perms.matrix(db),
        "locked": [{"role": r, "permission": p} for r, p in sorted(perms.LOCKED)],
    }


# PUBLIC_INTERFACE
@router.get("/permissions", response_model=PermissionMatrixOut, summary="Get the permission matrix")
def get_permissions(db: Session = Depends(get_db), _: User = Depends(require_permission("permissions.manage"))):
    """Return the effective role permission matrix, the catalogue and locked entries."""
    return _view(db)


# PUBLIC_INTERFACE
@router.put("/permissions", response_model=PermissionMatrixOut, summary="Update the permission matrix",
            description="Partial updates are allowed. The administrator's permissions.manage cannot be removed.")
def put_permissions(body: PermissionMatrixIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("permissions.manage"))):
    """Apply role/permission changes; unknown roles or keys give 422, locked entries 422."""
    current = perms.matrix(db)
    changes = []
    for role, values in body.matrix.items():
        if role not in perms.ROLES:
            raise ApiError(422, "unknown_role", f"Unknown role {role!r}")
        for key, allowed in values.items():
            if key not in perms.PERMISSIONS:
                raise ApiError(422, "unknown_permission", f"Unknown permission {key!r}")
            if (role, key) in perms.LOCKED and not allowed:
                raise ApiError(422, "permission_locked", "The administrator must keep permissions.manage")
            if current[role][key] != allowed:
                changes.append((role, key, allowed))
    for role, key, allowed in changes:
        row = db.get(RolePermission, (role, key))
        if row is None:
            db.add(RolePermission(role=role, permission=key, allowed=allowed, updated_by=user.id))
        else:
            row.allowed = allowed
            row.updated_by = user.id
    audit.record(db, user.id, "permissions.update", "role_permissions", "matrix",
                 {"changes": [{"role": r, "permission": k, "allowed": a} for r, k, a in changes]})
    db.commit()
    return _view(db)
