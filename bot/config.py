"""Environment-backed configuration for the VAD Operations Bot."""

import json
import logging
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _parse_int_env(key: str) -> int | None:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning("%s is not a valid integer; ignored", key)
        return None


def _parse_ids(key: str) -> frozenset[int]:
    values = set()
    for raw in os.environ.get(key, "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            values.add(int(raw))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid Telegram ID in %s", key)
    return frozenset(values)


@dataclass
class Config:
    token: str
    admin_chat_id: int | None
    log_level: str
    owner_user_ids: frozenset[int]
    lead_admin_user_ids: frozenset[int]
    admin_user_ids: frozenset[int]
    admin_permissions: dict[int, frozenset[str]]
    girls_chat_id: int | None
    girls_thread_id: int | None
    pop_thread_id: int | None
    reports_thread_id: int | None
    timezone_name: str
    warning_hours: int
    alert_hours: int
    setup_mode: bool

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. Add it as a Replit Secret.")
        timezone_name = os.environ.get("TIMEZONE", "America/New_York")
        ZoneInfo(timezone_name)
        try:
            raw_permissions = json.loads(os.environ.get("ADMIN_PERMISSIONS_JSON", "{}"))
            admin_permissions = {
                int(user_id): frozenset(map(str, permissions))
                for user_id, permissions in raw_permissions.items()
            }
        except (ValueError, TypeError, json.JSONDecodeError):
            logging.getLogger(__name__).warning("ADMIN_PERMISSIONS_JSON is invalid; defaults used")
            admin_permissions = {}
        owners = _parse_ids("OWNER_USER_IDS") | _parse_ids("OWNER_TELEGRAM_IDS")
        return cls(
            token=token,
            admin_chat_id=_parse_int_env("ADMIN_CHAT_ID"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            owner_user_ids=frozenset(owners),
            lead_admin_user_ids=_parse_ids("LEAD_ADMIN_USER_IDS"),
            admin_user_ids=_parse_ids("ADMIN_USER_IDS"),
            admin_permissions=admin_permissions,
            girls_chat_id=_parse_int_env("GIRLS_CHAT_ID"),
            girls_thread_id=_parse_int_env("GIRLS_THREAD_ID"),
            pop_thread_id=_parse_int_env("POP_THREAD_ID"),
            reports_thread_id=_parse_int_env("REPORTS_THREAD_ID"),
            timezone_name=timezone_name,
            warning_hours=int(os.environ.get("INACTIVITY_WARNING_HOURS", "48")),
            alert_hours=int(os.environ.get("INACTIVITY_ALERT_HOURS", "72")),
            setup_mode=os.environ.get("SETUP_MODE", "false").strip().casefold() == "true",
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


RESOURCE_DEFAULTS = {
    "rules": ("Community Rules", "Community rules are maintained by the owner team."),
    "creator_guide": ("Creator Guide", "Use the Creator dashboard to manage your operations profile."),
    "engagement": ("How Engagement Is Counted", "Meaningful conversation counts; spam, greetings, repeats, and filler do not."),
    "vacation": ("Vacation Policy", "Submit dates in advance when possible. Approval pauses applicable expectations."),
    "sick": ("Sick-Day Policy", "Report only dates and an optional note; medical details are never required."),
    "pop": ("Thursday POP Instructions", "Submit proof in the configured Thursday POP topic."),
    "faq": ("Frequently Asked Questions", "Contact an administrator if your question is not answered here."),
    "contact": ("Contact Admin", "Use Contact Admin from your Creator dashboard."),
}
