"""
Configuration and menu data for VAD Coffee Lounge Bot.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    token: str
    admin_chat_id: int | None
    coffee_orders_thread_id: int | None
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set. Add it as a Replit Secret.")

        def _parse_int_env(key: str) -> int | None:
            raw = os.environ.get(key, "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except ValueError:
                import logging
                logging.getLogger(__name__).warning(
                    "%s %r is not a valid integer — ignored.", key, raw
                )
                return None

        return cls(
            token=token,
            admin_chat_id=_parse_int_env("ADMIN_CHAT_ID"),
            coffee_orders_thread_id=_parse_int_env("COFFEE_ORDERS_THREAD_ID"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        )


# ── Menu data ──────────────────────────────────────────────────────────────

BARISTAS = [
    "Leah", "Jade", "Asobi", "Lia", "Jude", "Nicole",
    "Alex", "Maria", "Darla", "Eve", "Bambola", "Kayt",
    "Kira", "Keely", "Kayla", "Hilarity", "Peppi", "Ashley",
    "Queen Anie", "J💜",
]

SIZES = {
    "tall":   {"label": "Quick Coffee Date", "duration": "30 minutes", "price": 30},
    "grande": {"label": "Cozy Coffee Date",  "duration": "1 hour",     "price": 60},
    "venti":  {"label": "VIP Coffee Date",   "duration": "2 hours",    "price": 120},
}

ROASTS = {
    "light":  {"label": "Light Roast",  "price": 10, "description": "Sweet & smooth (sfw banter, flirting & company)"},
    "medium": {"label": "Medium Roast", "price": 20, "description": "Playful middle ground (casual and sexual mix)"},
    "dark":   {"label": "Dark Roast",   "price": 40, "description": "Extra hot 🔥 (intense sexual chemistry)"},
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
    STATE_WELCOME,
    STATE_BARISTAS,
    STATE_SIZE,
    STATE_ROAST,
    STATE_FLAVORS,
    STATE_BAKERY,
    STATE_CAFFEINE,
    STATE_RECEIPT,
) = range(8)
