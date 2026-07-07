"""
Configuration module for VAD Coffee Date Bot.
Reads settings from environment variables.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Bot configuration loaded from environment variables."""

    token: str
    admin_ids: list[int]
    log_level: str
    debug: bool

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN environment variable is not set. "
                "Add it as a secret in Replit."
            )

        raw_admin_ids = os.environ.get("ADMIN_IDS", "")
        admin_ids: list[int] = []
        if raw_admin_ids:
            try:
                admin_ids = [int(i.strip()) for i in raw_admin_ids.split(",") if i.strip()]
            except ValueError:
                pass

        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        debug = os.environ.get("DEBUG", "false").lower() == "true"

        return cls(
            token=token,
            admin_ids=admin_ids,
            log_level=log_level,
            debug=debug,
        )


# Conversation states
(
    STATE_ASKING_NAME,
    STATE_ASKING_AVAILABILITY,
    STATE_ASKING_LOCATION,
    STATE_ASKING_INTERESTS,
    STATE_CONFIRMING,
) = range(5)

# Callback data constants
CB_CONFIRM_YES = "confirm_yes"
CB_CONFIRM_NO = "confirm_no"
CB_CANCEL = "cancel"

AVAILABILITY_OPTIONS = [
    "Weekday mornings",
    "Weekday afternoons",
    "Weekday evenings",
    "Weekend mornings",
    "Weekend afternoons",
    "Weekend evenings",
]

INTEREST_OPTIONS = [
    "Specialty coffee ☕",
    "Tech & startups 💻",
    "Arts & culture 🎨",
    "Business & networking 💼",
    "Fitness & wellness 🏃",
    "Food & travel 🍜",
    "Reading & writing 📚",
    "Music 🎵",
]
