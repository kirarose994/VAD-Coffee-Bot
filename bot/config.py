"""
Configuration and menu data for VAD Coffee Lounge Bot.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    token: str
    admin_chat_id: int | None
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. Add it as a Replit Secret.")

        raw_admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
        admin_chat_id: int | None = None
        if raw_admin:
            try:
                admin_chat_id = int(raw_admin)
            except ValueError:
                import logging
                logging.getLogger(__name__).warning(
                    "ADMIN_CHAT_ID %r is not a valid integer — admin forwarding disabled.", raw_admin
                )

        return cls(
            token=token,
            admin_chat_id=admin_chat_id,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )


# ── Menu data ──────────────────────────────────────────────────────────────

BARISTAS = [
    "Leah", "Jade", "Asobi", "Lia", "Jude", "Nicole",
    "Alex", "Maria", "Darla", "Eve", "Bambola", "Kayt",
    "Kira", "Keely", "Kayla", "Hilarity", "Peppi", "Ashley",
]

SIZES = {
    "tall":   {"label": "Tall",   "duration": "30 minutes", "price": 30},
    "grande": {"label": "Grande", "duration": "1 hour",     "price": 60},
    "venti":  {"label": "Venti",  "duration": "2 hours",    "price": 120},
}

ROASTS = {
    "light":  {"label": "Light Roast",  "price": 10},
    "medium": {"label": "Medium Roast", "price": 20},
    "dark":   {"label": "Dark Roast",   "price": 40},
}

FLAVORS = {
    "vanilla":   {"label": "Vanilla",   "price": 0},
    "caramel":   {"label": "Caramel",   "price": 0},
    "hazelnut":  {"label": "Hazelnut",  "price": 0},
    "cinnamon":  {"label": "Cinnamon",  "price": 15},
}

BAKERY = {
    "croissant": {"label": "Croissant",          "duration": "3 days", "price": 75},
    "cakepop":   {"label": "Cake Pop",           "duration": "5 days", "price": 150},
    "sandwich":  {"label": "Breakfast Sandwich", "duration": "7 days", "price": 200},
}

# ── Conversation states ────────────────────────────────────────────────────

(
    STATE_BARISTAS,
    STATE_SIZE,
    STATE_ROAST,
    STATE_FLAVORS,
    STATE_BAKERY,
    STATE_CAFFEINE,
    STATE_RECEIPT,
) = range(7)
