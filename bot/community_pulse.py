"""Calm, owner-only daily community summary built from existing status sources."""

from community_snapshot import actionable_total, build_snapshot, pop_attention
from participation_summary import build_participation_summary


def build_community_pulse(config,now=None,path=None):
    participation=build_participation_summary(config,now,path)
    snapshot=build_snapshot(config,now,path)
    pop=snapshot["pop"]
    pop_due_or_attention=(len(pop.get("due_today",[]))+len(pop.get("still_needed",[]))+len(pop_attention(snapshot)))
    attention=actionable_total(snapshot)
    return {"active_today":participation["today"]["creators"],
        "active_creators":len(snapshot["creators"]["approved"]),"events":participation["today"]["events"],
        "away_today":participation["today"]["away"],"still":len([r for r in participation["creators"] if not r["today_count"] and not r["away"]]),
        "pop_attention":pop_due_or_attention,"approaching":len(snapshot["participation"]["approaching"]),
        "attention":attention}


def render_community_pulse(pulse):
    calm=("Everything else looks healthy today." if not pulse["attention"]
        else "A few items may need a friendly follow-up.")
    return ("💚 Community Pulse\n\nA calm view of today’s community activity and follow-up needs.\n\n"
        f"👥 Active today: {pulse['active_today']} / {pulse['active_creators']}\n"
        f"💬 Meaningful participation events: {pulse['events']}\n"
        f"🌴 Away today: {pulse['away_today']}\n"
        f"📸 POP due or needing review: {pulse['pop_attention']}\n"
        f"💛 Friendly reminders approaching: {pulse['approaching']}\n"
        f"📥 Items needing attention: {pulse['attention']}\n\n{calm}")
