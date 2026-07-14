"""Central operational destination map and failure-safe Telegram delivery."""

import secrets

import database as db


ROUTES = {
    "registration": ("admin_chat_id","registration_thread_id","reports_thread_id"),
    "away_notice": ("admin_chat_id","away_thread_id","reports_thread_id"),
    "pop_review": ("admin_chat_id","pop_review_thread_id","reports_thread_id"),
    "participation_flag": ("admin_chat_id","reports_thread_id",None),
    "participation_alert": ("admin_chat_id","reports_thread_id",None),
    "moderation": ("admin_chat_id","moderation_thread_id","reports_thread_id"),
    "support": ("admin_chat_id","support_thread_id","reports_thread_id"),
    "owner_review": ("admin_chat_id","owner_review_thread_id","reports_thread_id"),
    "health": ("admin_chat_id","health_thread_id","reports_thread_id"),
    "announcement": ("admin_chat_id","reports_thread_id",None),
}


def destination(config,event_type):
    chat_attr,thread_attr,fallback_attr=ROUTES[event_type]
    chat_id=getattr(config,chat_attr,None)
    thread_id=getattr(config,thread_attr,None)
    if thread_id is None and fallback_attr:
        thread_id=getattr(config,fallback_attr,None)
    return chat_id,thread_id


async def send_routed(bot,config,event_type,text,*,reply_markup=None,payload_summary=None,
                      target_telegram_id=None,related_request_id=None,related_submission_id=None):
    """Send once to a configured route and durably record failures for owner review."""
    chat_id,thread_id=destination(config,event_type)
    if chat_id is None:
        error_ref="ROUTE-"+secrets.token_hex(4).upper()
        db.record_delivery_failure(error_ref,event_type,None,thread_id,payload_summary or "Destination not configured")
        db.record_audit(None,"routed_delivery_failed","notification",target_telegram_id=target_telegram_id,
            related_request_id=related_request_id,related_submission_id=related_submission_id,result="error",error_reference=error_ref)
        return False,error_ref
    try:
        await bot.send_message(chat_id,text,message_thread_id=thread_id,reply_markup=reply_markup)
        db.set_system_state("last_admin_notification",event_type)
        db.record_audit(None,"routed_delivery_succeeded","notification",target_telegram_id=target_telegram_id,
            related_request_id=related_request_id,related_submission_id=related_submission_id,new_value={"event":event_type})
        return True,None
    except Exception:
        error_ref="DEL-"+secrets.token_hex(4).upper()
        db.record_delivery_failure(error_ref,event_type,chat_id,thread_id,payload_summary or text[:120])
        return False,error_ref


def routing_summary(config):
    return [(event,*destination(config,event)) for event in ROUTES]
