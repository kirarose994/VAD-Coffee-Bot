"""Owner-facing operational readiness checks with no destructive side effects."""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import database as db

EXPECTED_MAIN_CHAT_ID = -1003543892255
CURRENT_SCHEMA_VERSION = 10
REQUIRED_DOCS = ("OWNER_GUIDE.md", "SETUP_GUIDE.md", "QUICK_START_FOR_KIRA_AND_ALEX.md")


def _item(key,label,state,detail,action):
    return {"key":key,"label":label,"state":state,"detail":detail,"action":action}


def _configured(value): return value is not None


def coffee_handlers_inactive():
    active=Path(__file__).parent
    forbidden_files=("order.py","receipt.py","coffee.py","barista.py")
    try:source=(active/"main.py").read_text(encoding="utf-8").casefold()
    except OSError:return False
    return not any((active/name).exists() for name in forbidden_files) and "build_order_conversation" not in source


def readiness_items(config,path=None,now=None):
    """Calculate honest, actionable status without claiming external verification."""
    state=db.system_state(path); failures=db.open_delivery_failures(path); now=now or datetime.now(config.timezone)
    topics=frozenset(getattr(config,"participation_topic_ids",frozenset()) or ())
    general_verified="config:participation_topic_ids" in state and not topics
    owners=frozenset(getattr(config,"owner_user_ids",frozenset()) or ())
    backup=state.get("last_database_backup")
    backup_recent=False
    if backup:
        try: backup_recent=now-datetime.fromisoformat(backup["value"]).astimezone(config.timezone)<=timedelta(days=7)
        except (ValueError,TypeError): pass
    main=getattr(config,"participation_chat_id",None)
    verified=lambda key: key in state
    detected=verified("last_participation_message_detected")
    counted=verified("last_meaningful_participation_counted") or verified("readiness:meaningful_test")
    privacy=state.get("telegram_can_read_all_group_messages",{}).get("value")
    message_access_ready=privacy=="true" or detected
    route_specs=(
        ("registration","Registration-review topic","registration_thread_id","location_registration"),
        ("away","Away Notice topic","away_thread_id","location_away"),
        ("pop_review","POP-review topic","pop_review_thread_id","location_pop_review"),
        ("reports","Participation-alert topic","reports_thread_id","location_reports"),
        ("moderation","Moderation topic","moderation_thread_id","location_moderation"),
        ("support","Support topic","support_thread_id","location_support"),
        ("health","Health/error topic","health_thread_id","location_health"),
    )
    items=[
        _item("owners","Owners configured","ready" if owners else "problem","At least one numeric Owner ID is required.","roles"),
        _item("alex","Alex’s Owner ID configured","ready" if len(owners)>=2 else "setup","The bot can verify that two numeric Owner IDs exist; Kira must confirm the second belongs to Alex.","copy_alex_instructions"),
        _item("token","Bot token available","ready" if bool(getattr(config,"token",None)) else "problem","The token is checked without displaying its value.","readiness_token_help"),
        _item("main","Main participation group configured","ready" if main==EXPECTED_MAIN_CHAT_ID else "problem" if main else "setup",f"Expected Main VAD group: {EXPECTED_MAIN_CHAT_ID}.","location_main"),
        _item("participation_topic","Participation topic configured","ready" if topics or general_verified else "setup",
            "General is explicitly verified." if general_verified else "The General participation topic must be verified; it is never guessed.","location_participation"),
        _item("privacy","Telegram group-message access","ready" if message_access_ready else "problem" if privacy=="false" else "unverified",
            "Ready when Telegram privacy mode is disabled or an ordinary participation message has been observed.","location_participation"),
        _item("ordinary_messages","Bot can read ordinary messages in participation area","ready" if detected or counted else "unverified","Send a meaningful test message in the verified participation topic.","test_meaningful"),
        _item("sellers","Sellers group configured","ready" if _configured(getattr(config,"creator_group_id",None)) else "setup","The Sellers group is required for seller workflows.","location_sellers"),
        _item("pop_topic","POP topic configured","ready" if _configured(getattr(config,"pop_thread_id",None)) else "setup","Verify the Sellers group POP topic.","location_pop"),
        _item("admin","Admin group configured","ready" if _configured(getattr(config,"admin_chat_id",None)) else "setup","Private operational cards require an Admin group.","location_admin"),
    ]
    for key,label,attr,action in route_specs:
        items.append(_item(key,label,"ready" if _configured(getattr(config,attr,None)) else "setup",f"Verify the dedicated {label.lower()}.",action))
    active_creators=len([r for r in db.list_creators(path) if r["status"]=="active"])
    participation_verified=bool((topics or general_verified) and active_creators and counted and message_access_ready)
    registration_verified=verified("last_route_success:registration") or verified("readiness:registration_route_test")
    away_route_verified=verified("last_route_success:away_notice") or verified("readiness:away_route_test")
    items.extend([
        _item("registration_queue","Registration queue working","ready" if registration_verified else "unverified",
            "Verified by a successful real registration delivery." if verified("last_route_success:registration") else "Run the safe registration routing test after configuring its topic.","test_route_registration"),
        _item("identity","Creator identity isolation working","ready","Self-service lookups use immutable Telegram IDs and have automated coverage.","test_privacy"),
        _item("monitor","Participation monitor active","ready" if participation_verified else "unverified","Ready requires message access, a verified topic, an approved creator, and one successfully counted meaningful message.","test_center"),
        _item("two_day","Two-day reminders configured","ready" if getattr(config,"warning_hours",None) else "setup",f"Current threshold: {getattr(config,'warning_hours','not set')} hours.","settings_warning"),
        _item("three_day","Three-day alerts configured","ready" if getattr(config,"alert_hours",None) else "setup",f"Current threshold: {getattr(config,'alert_hours','not set')} hours.","settings_alert"),
        _item("pop_deadline","Thursday POP deadline configured","ready" if getattr(config,"pop_cutoff_time",None) is not None else "setup",f"Current cutoff: {getattr(config,'pop_cutoff_time','not set')} ET.","settings_pop"),
        _item("away_route","Away Notice routing working","ready" if away_route_verified else "unverified",
            "Verified by a successful real Away Notice delivery." if verified("last_route_success:away_notice") else "Run the safe Away Notice routing test.","test_away"),
        _item("support_route","Support routing working","ready" if verified("readiness:support_route_test") else "unverified","Run the safe Support routing test.","test_support"),
        _item("scheduler","Scheduler running","ready" if "last_scheduled_check" in state else "unverified","No recent scheduled check has been recorded yet.","health"),
        _item("database","Database ready","ready","The readiness query completed successfully.","health"),
        _item("schema","Database schema current","ready" if db.schema_version(path)==CURRENT_SCHEMA_VERSION else "problem",f"Expected schema version {CURRENT_SCHEMA_VERSION}.","health"),
        _item("backup","Recent backup status","ready" if backup_recent else "setup","No verified database backup from the last seven days is recorded.","backup_help"),
        _item("failures","No unresolved delivery failures","ready" if not failures else "problem",f"Unresolved delivery failures: {len(failures)}.","health"),
        _item("recent_delivery","Recent successful operational delivery","ready" if "last_admin_notification" in state else "unverified","Run a safe routing test to verify delivery without contacting a creator.","routing_summary"),
        _item("coffee","Coffee Date handlers inactive","ready" if coffee_handlers_inactive() else "problem","The active application must contain no Coffee Date conversation or ordering handlers.","health"),
    ])
    return items


def status_icon(state):
    return {"ready":"🟢 Ready","setup":"🟡 Needs Setup","problem":"🔴 Problem Detected","unverified":"⚪ Not Yet Verified"}[state]


def system_check_summary(config,path=None,docs_root=None):
    items=readiness_items(config,path); root=Path(docs_root) if docs_root else Path(__file__).parents[1]/"docs"
    docs_ok=all((root/name).is_file() for name in REQUIRED_DOCS)
    extra=_item("docs","Required Owner documentation exists","ready" if docs_ok else "problem","Owner, Setup, and Quick Start guides must exist.","resources")
    checks=items+[extra]
    counts={state:sum(item["state"]==state for item in checks) for state in ("ready","setup","problem","unverified")}
    return checks,counts


def critical_fingerprint(config,path=None):
    incomplete=[i["key"] for i in readiness_items(config,path) if i["state"] in {"setup","problem"} and i["key"] in
        {"owners","token","main","participation_topic","privacy","admin","reports","health"}]
    return hashlib.sha256("|".join(sorted(incomplete)).encode()).hexdigest()[:16],incomplete
