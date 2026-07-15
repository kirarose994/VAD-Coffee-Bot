"""Environment-backed configuration for the VAD Operations Bot."""

import json
import logging
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from constants import (DEFAULT_ALERT_HOURS, DEFAULT_MIN_MEANINGFUL_CHARACTERS,
    DEFAULT_MIN_MEANINGFUL_WORDS, DEFAULT_POP_CUTOFF, DEFAULT_POP_DUE_WEEKDAY,
    DEFAULT_REPEAT_WINDOW_DAYS, DEFAULT_TIMEZONE, DEFAULT_WARNING_HOURS)


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
    daily_owner_summary_enabled: bool
    daily_owner_summary_time: str
    pop_due_weekday: int
    pop_cutoff_time: str
    registration_thread_id: int | None
    away_thread_id: int | None
    moderation_thread_id: int | None
    health_thread_id: int | None
    participation_chat_id: int | None = None
    participation_topic_ids: frozenset[int] = field(default_factory=frozenset)
    pop_chat_id: int | None = None
    creator_group_id: int | None = None
    buyer_group_id: int | None = None
    meaningful_min_words: int = DEFAULT_MIN_MEANINGFUL_WORDS
    meaningful_min_characters: int = DEFAULT_MIN_MEANINGFUL_CHARACTERS
    repeat_window_days: int = DEFAULT_REPEAT_WINDOW_DAYS
    pop_review_thread_id: int | None = None
    support_thread_id: int | None = None
    owner_review_thread_id: int | None = None
    daily_brief_enabled: bool = False
    daily_brief_time: str = "09:00"
    daily_brief_chat_id: int | None = None
    daily_brief_thread_id: int | None = None
    daily_brief_include_health: bool = True
    daily_brief_include_zero: bool = True
    daily_brief_weekends: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. Add it as a Replit Secret.")
        timezone_name = os.environ.get("TIMEZONE", DEFAULT_TIMEZONE)
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
        legacy_admins = _parse_ids("LEAD_ADMIN_USER_IDS")
        girls_chat_id = _parse_int_env("GIRLS_CHAT_ID")
        girls_thread_id = _parse_int_env("GIRLS_THREAD_ID")
        participation_topics = set(_parse_ids("PARTICIPATION_TOPIC_IDS")) | set(_parse_ids("PARTICIPATION_THREAD_IDS"))
        explicit_participation_chat = _parse_int_env("PARTICIPATION_CHAT_ID") or _parse_int_env("MAIN_CHAT_ID")
        if not explicit_participation_chat and not participation_topics and girls_thread_id is not None:
            participation_topics.add(girls_thread_id)
        participation_chat_id = explicit_participation_chat or girls_chat_id
        return cls(
            token=token,
            admin_chat_id=_parse_int_env("ADMIN_CHAT_ID"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            owner_user_ids=frozenset(owners),
            # Retain an empty compatibility field for old database snapshots while converting
            # every legacy elevated administrator to the single Admin role.
            lead_admin_user_ids=frozenset(),
            admin_user_ids=(_parse_ids("ADMIN_USER_IDS") | legacy_admins) - owners,
            admin_permissions=admin_permissions,
            girls_chat_id=girls_chat_id,
            girls_thread_id=girls_thread_id,
            pop_thread_id=_parse_int_env("POP_THREAD_ID"),
            reports_thread_id=_parse_int_env("REPORTS_THREAD_ID"),
            timezone_name=timezone_name,
            warning_hours=int(os.environ.get("INACTIVITY_WARNING_HOURS", str(DEFAULT_WARNING_HOURS))),
            alert_hours=int(os.environ.get("INACTIVITY_ALERT_HOURS", str(DEFAULT_ALERT_HOURS))),
            daily_owner_summary_enabled=os.environ.get("DAILY_OWNER_SUMMARY_ENABLED", "false").strip().casefold() == "true",
            daily_owner_summary_time=os.environ.get("DAILY_OWNER_SUMMARY_TIME", "09:00"),
            pop_due_weekday=int(os.environ.get("POP_DUE_WEEKDAY", str(DEFAULT_POP_DUE_WEEKDAY))),
            pop_cutoff_time=os.environ.get("POP_CUTOFF_TIME", DEFAULT_POP_CUTOFF),
            registration_thread_id=_parse_int_env("REGISTRATION_THREAD_ID"),
            away_thread_id=_parse_int_env("AWAY_THREAD_ID"),
            moderation_thread_id=_parse_int_env("MODERATION_THREAD_ID"),
            health_thread_id=_parse_int_env("HEALTH_THREAD_ID"),
            participation_chat_id=participation_chat_id,
            participation_topic_ids=frozenset(participation_topics),
            pop_chat_id=_parse_int_env("POP_CHAT_ID") or girls_chat_id,
            creator_group_id=_parse_int_env("CREATOR_GROUP_ID") or girls_chat_id,
            buyer_group_id=_parse_int_env("BUYER_GROUP_ID"),
            meaningful_min_words=int(os.environ.get("MEANINGFUL_MIN_WORDS", str(DEFAULT_MIN_MEANINGFUL_WORDS))),
            meaningful_min_characters=int(os.environ.get("MEANINGFUL_MIN_CHARACTERS", str(DEFAULT_MIN_MEANINGFUL_CHARACTERS))),
            repeat_window_days=int(os.environ.get("MEANINGFUL_REPEAT_DAYS", str(DEFAULT_REPEAT_WINDOW_DAYS))),
            pop_review_thread_id=_parse_int_env("POP_REVIEW_THREAD_ID"),
            support_thread_id=_parse_int_env("SUPPORT_THREAD_ID"),
            owner_review_thread_id=_parse_int_env("OWNER_REVIEW_THREAD_ID"),
            daily_brief_enabled=os.environ.get("DAILY_ADMIN_BRIEF_ENABLED",os.environ.get("DAILY_OWNER_SUMMARY_ENABLED","false")).strip().casefold()=="true",
            daily_brief_time=os.environ.get("DAILY_ADMIN_BRIEF_TIME",os.environ.get("DAILY_OWNER_SUMMARY_TIME","09:00")),
            daily_brief_chat_id=_parse_int_env("DAILY_BRIEF_CHAT_ID") or _parse_int_env("ADMIN_CHAT_ID"),
            daily_brief_thread_id=_parse_int_env("DAILY_BRIEF_THREAD_ID") or _parse_int_env("REPORTS_THREAD_ID"),
            daily_brief_include_health=os.environ.get("DAILY_BRIEF_INCLUDE_HEALTH","true").strip().casefold()=="true",
            daily_brief_include_zero=os.environ.get("DAILY_BRIEF_INCLUDE_ZERO","true").strip().casefold()=="true",
            daily_brief_weekends=os.environ.get("DAILY_BRIEF_WEEKENDS","true").strip().casefold()=="true",
        )

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


RESOURCE_DEFAULTS = {
    "about": ("About This Bot", "Your VAD Community Hub keeps participation, Thursday POP, Away Notices, and personal updates together. Away Notices keep tracking fair; private details are never required."),
    "rules": ("Community Rules", "Community rules are maintained by the owner team."),
    "creator_guide": ("Creator Guide", "Use the Creator dashboard to manage your operations profile."),
    "engagement": ("Meaningful Participation", "Meaningful participation means contributing to genuine conversation that helps keep the community active and engaging. Respond thoughtfully, ask questions, join discussions, or otherwise add value. Greetings, check-ins, emojis, stickers, context-free photos, repeated messages, and promotional posts do not satisfy the participation requirement. The purpose is to help keep the community lively so members have a reason to come back."),
    "vacation": ("Away Notice Policy", "Let the community know when you will be away so participation and POP tracking remain fair. Participation is optional while you’re away. Meaningful messages will still count, but you will not be penalized for inactivity during your away period."),
    "sick": ("Personal-Day Privacy", "Share only dates and an optional note. Medical or other private details are never required."),
    "pop": ("Thursday POP Instructions", "Submit proof in the configured Thursday POP topic."),
    "faq": ("Frequently Asked Questions", "Contact an administrator if your question is not answered here."),
    "contact": ("Contact Admin", "Use Contact Admin from your Creator dashboard."),
    "admin_registrations": ("Review New Creators", "Review identity details, then approve or decline. The creator receives the result and the decision is audited."),
    "admin_pop": ("Review POP", "Use POP Reviews for submissions awaiting a decision. Every decision is recorded and sent privately to the creator."),
    "admin_away": ("Review Away Notices", "Acknowledge and update status, ask for clarification, or mark a notice invalid. Original details remain in history."),
    "admin_alerts": ("Participation Alerts", "Use alerts for supportive follow-up. The bot never removes a member automatically."),
    "admin_support": ("Support Requests", "Assign creator questions, respond, escalate when needed, and resolve them without exposing private details."),
    "owner_locations": ("Telegram Locations", "Verify groups and topics from inside Telegram, preview the match, and confirm before saving routing changes."),
    "owner_monitor": ("Participation Monitor", "Confirm that the approved participation area is connected and review concise counted, ignored, and failure totals."),
    "owner_audit": ("Audit and Recovery", "The append-oriented audit trail records protected actions. Only owners can view full actor identities, archives, and restoration tools."),
}
