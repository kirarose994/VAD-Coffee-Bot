"""Preview-only, non-competitive creator encouragement."""


def render_weekly_encouragement(creator):
    pop=creator.get("pop_status","not_due").replace("_"," ").title()
    away=" Your Away Notice kept expectations paused when you needed time away." if creator.get("away_used") else ""
    return ("🌸 Weekly Community Update\n\n"
        f"Thank you for helping keep VAD active this week, {creator['display_name']}.\n\n"
        f"Meaningful participation: {'Recorded this week' if creator.get('week_count',0) else 'No activity summary yet'}\nThursday POP: {pop}\n\n"
        "Regular conversation helps keep the community lively and welcoming for creators and clients."
        f"{away}\n\nThis is a private preview. It is not a ranking and does not reward message volume.")
