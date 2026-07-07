"""
Message formatting helpers for VAD Coffee Date Bot.
"""


def format_profile_summary(profile: dict) -> str:
    """Return a nicely formatted profile summary for confirmation."""
    name = profile.get("name", "—")
    availability = profile.get("availability", [])
    location = profile.get("location", "—")
    interests = profile.get("interests", [])

    avail_text = "\n".join(f"  • {a}" for a in availability) if availability else "  • None selected"
    interests_text = "\n".join(f"  • {i}" for i in interests) if interests else "  • None selected"

    return (
        "☕ <b>Your Coffee Date Profile</b>\n\n"
        f"<b>Name:</b> {name}\n\n"
        f"<b>Location / Area:</b> {location}\n\n"
        f"<b>Availability:</b>\n{avail_text}\n\n"
        f"<b>Interests:</b>\n{interests_text}"
    )


def format_welcome(first_name: str) -> str:
    return (
        f"☕ <b>Welcome to VAD Coffee Date Bot, {first_name}!</b>\n\n"
        "I help connect people for casual coffee chats and networking.\n\n"
        "<b>What I can do:</b>\n"
        "• /register — Set up your coffee date profile\n"
        "• /profile — View your current profile\n"
        "• /match — Find your next coffee partner\n"
        "• /help — Show all commands\n\n"
        "Ready to grab coffee? Start with /register! ☕"
    )


def format_help() -> str:
    return (
        "☕ <b>VAD Coffee Date Bot — Commands</b>\n\n"
        "/start — Welcome message\n"
        "/register — Create or update your coffee date profile\n"
        "/profile — View your saved profile\n"
        "/match — Get matched with a coffee partner\n"
        "/cancel — Cancel the current action\n"
        "/help — Show this help message\n\n"
        "<i>Tip: Use /register first to set up your availability and interests!</i>"
    )
