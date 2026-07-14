"""Role-based authorization for Telegram commands."""

from enum import IntEnum


class Role(IntEnum):
    NONE = 0
    ADMIN = 1
    LEAD_ADMIN = 2


def role_for(user_id: int | None, config) -> Role:
    if user_id is None:
        return Role.NONE
    if user_id in config.lead_admin_user_ids:
        return Role.LEAD_ADMIN
    if user_id in config.admin_user_ids:
        return Role.ADMIN
    return Role.NONE


def can_read(user_id: int | None, config) -> bool:
    return role_for(user_id, config) >= Role.ADMIN


def can_mutate(user_id: int | None, config) -> bool:
    return role_for(user_id, config) is Role.LEAD_ADMIN
