"""Role-based authorization for Telegram commands."""

from enum import IntEnum, StrEnum


class Membership(StrEnum):
    CREATOR = "creator"
    ADMIN = "admin"
    OWNER = "owner"


class Role(IntEnum):
    NONE = 0
    ADMIN = 1
    OWNER = 2


def role_for(user_id: int | None, config) -> Role:
    if user_id is None:
        return Role.NONE
    if user_id in config.owner_user_ids:
        return Role.OWNER
    legacy_leads = getattr(config, "lead_admin_user_ids", frozenset())
    if user_id in config.admin_user_ids or user_id in legacy_leads:
        return Role.ADMIN
    return Role.NONE


def roles_for(user_id: int | None, config, *, has_creator_profile=False) -> frozenset[Membership]:
    """Return additive public memberships while preserving legacy permission tiers."""
    if user_id is None:
        return frozenset()
    memberships=set()
    highest=role_for(user_id,config)
    if has_creator_profile or highest >= Role.ADMIN:
        memberships.add(Membership.CREATOR)
    if highest >= Role.ADMIN:
        memberships.add(Membership.ADMIN)
    if highest is Role.OWNER:
        memberships.add(Membership.OWNER)
    return frozenset(memberships)


def can_read(user_id: int | None, config) -> bool:
    return role_for(user_id, config) >= Role.ADMIN


def can_mutate(user_id: int | None, config) -> bool:
    """Owners and admins may perform operational changes."""
    return role_for(user_id, config) >= Role.ADMIN


def can_view_audit(user_id: int | None, config) -> bool:
    """Private audit data, including actor identities, is owner-only."""
    return role_for(user_id, config) is Role.OWNER


def can_manage_sensitive(user_id: int | None, config) -> bool:
    """History, permissions, owners, and configuration are owner-only."""
    return role_for(user_id, config) is Role.OWNER


ADMIN_DEFAULT_PERMISSIONS = frozenset({
    "review_registrations", "review_vacations", "review_sick_days", "review_pop",
    "view_creator_reports", "manage_creators", "add_admin_notes", "send_announcements",
    "adjust_warnings",
    "manage_support",
})

def has_permission(user_id: int | None, config, permission: str) -> bool:
    role = role_for(user_id, config)
    if role is Role.OWNER:
        return True
    if role < Role.ADMIN:
        return False
    assigned = getattr(config, "admin_permissions", {}).get(user_id)
    return permission in (assigned if assigned is not None else ADMIN_DEFAULT_PERMISSIONS)
