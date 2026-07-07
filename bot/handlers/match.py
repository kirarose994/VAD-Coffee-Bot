"""
/match command handler — finds a coffee date partner based on shared interests and availability.
"""

import logging
import random
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _overlap_score(profile_a: dict, profile_b: dict) -> int:
    """Return a match score based on shared availability and interests."""
    avail_a = set(profile_a.get("availability", []))
    avail_b = set(profile_b.get("availability", []))
    interest_a = set(profile_a.get("interests", []))
    interest_b = set(profile_b.get("interests", []))
    return len(avail_a & avail_b) * 2 + len(interest_a & interest_b)


async def match_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /match command."""
    user = update.effective_user
    if user is None:
        return

    profiles: dict = context.bot_data.get("profiles", {})
    my_profile = profiles.get(user.id)

    if not my_profile:
        await update.message.reply_html(
            "You need a profile before you can match! Use /register first. ☕",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Find all other users with profiles
    candidates = {uid: p for uid, p in profiles.items() if uid != user.id}

    if not candidates:
        await update.message.reply_html(
            "No other users have registered yet — share the bot and come back soon! ☕",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Score and sort candidates
    scored = sorted(
        candidates.items(),
        key=lambda item: _overlap_score(my_profile, item[1]),
        reverse=True,
    )

    # Pick top match (or random from top-3 if tied)
    top_score = _overlap_score(my_profile, scored[0][1])
    top_candidates = [(uid, p) for uid, p in scored if _overlap_score(my_profile, p) == top_score]
    matched_uid, matched_profile = random.choice(top_candidates)

    matched_name = matched_profile.get("name", "Someone")
    matched_location = matched_profile.get("location", "Unknown area")
    matched_avail = matched_profile.get("availability", [])
    matched_interests = matched_profile.get("interests", [])

    shared_avail = set(my_profile.get("availability", [])) & set(matched_avail)
    shared_interests = set(my_profile.get("interests", [])) & set(matched_interests)

    avail_text = "\n".join(f"  • {a}" for a in shared_avail) if shared_avail else "  • (Check individually)"
    interests_text = "\n".join(f"  • {i}" for i in shared_interests) if shared_interests else "  • (Explore new ones!)"

    logger.info("Matched user %d with user %d", user.id, matched_uid)

    await update.message.reply_html(
        f"☕ <b>You've got a coffee match!</b>\n\n"
        f"<b>Name:</b> {matched_name}\n"
        f"<b>Area:</b> {matched_location}\n\n"
        f"<b>Shared availability:</b>\n{avail_text}\n\n"
        f"<b>Shared interests:</b>\n{interests_text}\n\n"
        f"<i>Reach out and set up that coffee chat! 🤝</i>",
        reply_markup=ReplyKeyboardRemove(),
    )
