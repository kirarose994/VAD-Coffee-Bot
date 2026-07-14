"""Shared product defaults and internal setting keys.

Values that operators may change are defaults only. Runtime configuration comes from the
environment and may be overridden by owner-approved settings stored in SQLite.
"""

DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_WARNING_HOURS = 48
DEFAULT_ALERT_HOURS = 72
DEFAULT_POP_DUE_WEEKDAY = 3  # Python weekday: Thursday
DEFAULT_POP_CUTOFF = "23:59"
DEFAULT_MIN_MEANINGFUL_WORDS = 3
DEFAULT_MIN_MEANINGFUL_CHARACTERS = 12
DEFAULT_REPEAT_WINDOW_DAYS = 7

SETTING_PREFIX = "config:"
PERSISTED_SETTING_ATTRIBUTES = {
    "participation_chat_id": "participation_chat_id",
    "participation_topic_ids": "participation_topic_ids",
    "pop_chat_id": "pop_chat_id",
    "pop_thread_id": "pop_thread_id",
    "admin_chat_id": "admin_chat_id",
    "creator_group_id": "creator_group_id",
    "buyer_group_id": "buyer_group_id",
    "timezone_name": "timezone_name",
    "warning_hours": "warning_hours",
    "alert_hours": "alert_hours",
    "pop_cutoff_time": "pop_cutoff_time",
    "meaningful_min_words": "meaningful_min_words",
    "meaningful_min_characters": "meaningful_min_characters",
    "repeat_window_days": "repeat_window_days",
    "pop_review_thread_id": "pop_review_thread_id",
    "support_thread_id": "support_thread_id",
    "owner_review_thread_id": "owner_review_thread_id",
    "reports_thread_id": "reports_thread_id",
    "away_thread_id": "away_thread_id",
    "registration_thread_id": "registration_thread_id",
    "moderation_thread_id": "moderation_thread_id",
    "health_thread_id": "health_thread_id",
    "admin_user_ids": "admin_user_ids",
    "lead_admin_user_ids": "lead_admin_user_ids",
}
