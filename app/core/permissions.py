"""Role definitions and RBAC helpers."""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    KJ = "kj"
    SINGER = "singer"
    OWNER = "owner"
    ACCOUNT = "account"

    @classmethod
    def from_string(cls, value: str) -> Role | None:
        try:
            return cls(value.lower())
        except ValueError:
            return None


# Each role maps to the set of roles it is permitted to act as.
# Used for hierarchical checks (admin can do anything an owner or kj can do).
# ACCOUNT is intentionally outside the venue hierarchy; it is checked separately.
ROLE_HIERARCHY: dict[Role, set[Role]] = {
    Role.ADMIN: {Role.ADMIN, Role.OWNER, Role.KJ, Role.SINGER},
    Role.OWNER: {Role.OWNER, Role.KJ, Role.SINGER},
    Role.KJ:    {Role.KJ, Role.SINGER},
    Role.SINGER:{Role.SINGER},
    Role.ACCOUNT: {Role.ACCOUNT},
}


def has_role(user_role: Role, required: Role | set[Role]) -> bool:
    """Check if user_role has authority to act as required."""
    permitted = ROLE_HIERARCHY.get(user_role, set())
    if isinstance(required, set):
        return bool(permitted & required)
    return required in permitted
