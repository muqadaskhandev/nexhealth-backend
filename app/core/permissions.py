"""Role-based capability definitions for practice staff.

Used by the API (invite validation) and mirrored in the frontend so admins
see exactly what each role can view, edit, create, or manage.
"""
from __future__ import annotations

from enum import Enum
from typing import TypedDict

from app.models.user import UserRole


class Capability(str, Enum):
    VIEW = "view"
    CREATE = "create"
    EDIT = "edit"
    MANAGE = "manage"


class PermissionRow(TypedDict):
    area: str
    description: str
    admin: Capability | None
    provider: Capability | None
    front_desk: Capability | None
    billing: Capability | None
    member: Capability | None


# Matrix of what each practice role can do in the product.
# `None` = no access. Keep this in sync with frontend `staffRoles.ts`.
PERMISSION_MATRIX: list[PermissionRow] = [
    {
        "area": "Patients",
        "description": "Search, open charts, create and update patient demographics",
        "admin": Capability.MANAGE,
        "provider": Capability.EDIT,
        "front_desk": Capability.EDIT,
        "billing": Capability.VIEW,
        "member": Capability.EDIT,
    },
    {
        "area": "Scheduling",
        "description": "Appointments, online booking, waitlist, recalls",
        "admin": Capability.MANAGE,
        "provider": Capability.EDIT,
        "front_desk": Capability.MANAGE,
        "billing": Capability.VIEW,
        "member": Capability.EDIT,
    },
    {
        "area": "Forms",
        "description": "Send intake/consent forms and review submissions",
        "admin": Capability.MANAGE,
        "provider": Capability.EDIT,
        "front_desk": Capability.EDIT,
        "billing": None,
        "member": Capability.EDIT,
    },
    {
        "area": "Communications",
        "description": "Messaging, reminders, and patient outreach",
        "admin": Capability.MANAGE,
        "provider": Capability.VIEW,
        "front_desk": Capability.EDIT,
        "billing": Capability.VIEW,
        "member": Capability.EDIT,
    },
    {
        "area": "Payments",
        "description": "Payment links, collections, and payment status",
        "admin": Capability.MANAGE,
        "provider": None,
        "front_desk": Capability.VIEW,
        "billing": Capability.MANAGE,
        "member": Capability.VIEW,
    },
    {
        "area": "Insurance verification",
        "description": "Eligibility checks before appointments",
        "admin": Capability.MANAGE,
        "provider": Capability.VIEW,
        "front_desk": Capability.EDIT,
        "billing": Capability.EDIT,
        "member": Capability.EDIT,
    },
    {
        "area": "Locations",
        "description": "Switch offices; admins can add and edit location details",
        "admin": Capability.MANAGE,
        "provider": Capability.VIEW,
        "front_desk": Capability.VIEW,
        "billing": Capability.VIEW,
        "member": Capability.VIEW,
    },
    {
        "area": "Staff & users",
        "description": "Invite staff, change roles, reset passwords, deactivate accounts",
        "admin": Capability.MANAGE,
        "provider": None,
        "front_desk": None,
        "billing": None,
        "member": None,
    },
    {
        "area": "Practice settings",
        "description": "Logo, Synchronizer / EHR connection, practice profile",
        "admin": Capability.MANAGE,
        "provider": None,
        "front_desk": None,
        "billing": None,
        "member": None,
    },
]

STAFF_ROLE_VALUES = frozenset(r.value for r in UserRole)

ROLE_LABELS: dict[str, str] = {
    UserRole.ADMIN.value: "Practice Admin",
    UserRole.PROVIDER.value: "Provider",
    UserRole.FRONT_DESK.value: "Front Desk",
    UserRole.BILLING.value: "Billing",
    UserRole.MEMBER.value: "Staff",
}

ROLE_SUMMARIES: dict[str, str] = {
    UserRole.ADMIN.value: "Full access to settings, staff, and all clinical tools.",
    UserRole.PROVIDER.value: "Clinical care — patients, scheduling, and forms; no practice settings.",
    UserRole.FRONT_DESK.value: "Front office — scheduling, patients, forms, and verification.",
    UserRole.BILLING.value: "Payments and insurance; limited clinical editing.",
    UserRole.MEMBER.value: "General staff access to day-to-day clinical tools.",
}


def normalize_staff_role(role: str | UserRole | None) -> UserRole:
    """Map an invite/API role string onto a known UserRole (default: member)."""
    if isinstance(role, UserRole):
        return role
    raw = (role or UserRole.MEMBER.value).strip().lower()
    try:
        return UserRole(raw)
    except ValueError:
        return UserRole.MEMBER


def role_can_manage_users(role: UserRole) -> bool:
    return role == UserRole.ADMIN
