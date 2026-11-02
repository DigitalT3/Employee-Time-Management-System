"""Configurable role permission matrix with defaults from specification section 5.5 (DEC-10)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RolePermission

ROLES = ("admin", "supervisor", "hr")

# key -> description (shown on the administrator permission page)
PERMISSIONS: dict[str, str] = {
    "dashboard.view": "View the supervisor dashboard",
    "attendance.view": "View attendance, sites and gates",
    "employees.view": "View employees",
    "employees.manage": "Register, edit and activate employees",
    "credentials.manage": "Block, unblock, revoke and re-issue QR credentials",
    "credentials.download": "Download and print QR codes",
    "attendance.correct": "Correct attendance sessions",
    "corrections.view": "View the correction audit",
    "reports.export": "View and export reports",
    "sites.manage": "Manage sites, gates, devices and attendance settings",
    "scanlog.view": "View the scan log and device status",
    "permissions.manage": "Change the permission matrix",
}

_ALL = {"admin", "supervisor", "hr"}
_ADMIN = {"admin"}
_ADMIN_SUP = {"admin", "supervisor"}
# Defaults follow the specification table; "as authorised" entries default to allowed
# for read-only functions and are configurable.
_DEFAULT_ROLES: dict[str, set[str]] = {
    "dashboard.view": _ALL,
    "attendance.view": _ALL,
    "employees.view": _ALL,
    "employees.manage": _ADMIN,
    "credentials.manage": _ADMIN,
    "credentials.download": _ADMIN,
    "attendance.correct": _ADMIN_SUP,
    "corrections.view": _ALL,
    "reports.export": _ALL,
    "sites.manage": _ADMIN,
    "scanlog.view": _ADMIN_SUP,
    "permissions.manage": _ADMIN,
}

# The administrator can never lose the right to repair the matrix.
LOCKED: frozenset[tuple[str, str]] = frozenset({("admin", "permissions.manage")})


# PUBLIC_INTERFACE
def default_allowed(role: str, permission: str) -> bool:
    """Return the built-in default for a role and permission."""
    return role in _DEFAULT_ROLES.get(permission, set())


# PUBLIC_INTERFACE
def matrix(db: Session) -> dict[str, dict[str, bool]]:
    """Return the effective matrix: stored overrides applied over the defaults."""
    result = {role: {key: default_allowed(role, key) for key in PERMISSIONS} for role in ROLES}
    for row in db.scalars(select(RolePermission)):
        if row.role in result and row.permission in PERMISSIONS:
            result[row.role][row.permission] = row.allowed
    for role, permission in LOCKED:
        result[role][permission] = True
    return result


# PUBLIC_INTERFACE
def effective_permissions(db: Session, role: str) -> list[str]:
    """Return the sorted list of permission keys granted to a role."""
    return sorted(key for key, allowed in matrix(db).get(role, {}).items() if allowed)


# PUBLIC_INTERFACE
def has_permission(db: Session, role: str, permission: str) -> bool:
    """Return whether a role currently holds a permission (no caching: changes apply at once)."""
    if (role, permission) in LOCKED:
        return True
    row = db.get(RolePermission, (role, permission))
    return row.allowed if row is not None else default_allowed(role, permission)
