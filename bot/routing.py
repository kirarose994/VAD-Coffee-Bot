"""Central operational destination map and failure-safe Telegram delivery."""

import secrets
import sqlite3
import traceback

import database as db
from telegram_io import is_transient_network_error, retry_telegram


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
    "daily_brief": ("daily_brief_chat_id","daily_brief_thread_id",None),
}

async def _notify_owners_once(bot,config,error_ref,event_type):
    for owner_id in getattr(config,"owner_user_ids",()):
        try:
            await retry_telegram(lambda owner_id=owner_id: bot.send_message(owner_id,f"⚠️ Delivery needs attention\n\nThe {event_type.replace('_',' ')} destination could not be reached. The original event was saved.\nReference: {error_ref}\n\nOpen Owner Home → Needs Attention."),attempts=2)
        except Exception:pass

def _record_transient_incident(error,event_type):
    reference="ERR-"+secrets.token_hex(4).upper();details={"exception_type":type(error).__name__,
        "message":str(error)[:2000],"traceback":"".join(traceback.format_exception(type(error),error,error.__traceback__))[-12000:],
        "source":f"routed_send:{event_type}"}
    incident,created=db.record_system_incident("transient_network:telegram",reference,"transient_network",details["source"],details)
    if created:
        db.record_audit(None,"system_error","system",target_record_id=incident["id"],result="error",
            reason="Transient Telegram/network read failure",new_value={**details,"incident_id":incident["id"]},
            error_reference=incident["error_reference"])
    return incident,created


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
        db.set_system_state(f"last_route_failure:{event_type}",error_ref)
        await _notify_owners_once(bot,config,error_ref,event_type)
        return False,error_ref
    try:
        await retry_telegram(lambda: bot.send_message(chat_id,text,message_thread_id=thread_id,reply_markup=reply_markup))
    except Exception as error:
        error_ref="DEL-"+secrets.token_hex(4).upper()
        db.record_delivery_failure(error_ref,event_type,chat_id,thread_id,payload_summary or text[:120])
        db.set_system_state(f"last_route_failure:{event_type}",error_ref)
        if is_transient_network_error(error):
            incident,created=_record_transient_incident(error,event_type)
            if created:await _notify_owners_once(bot,config,incident["error_reference"],"Telegram network")
        else:
            await _notify_owners_once(bot,config,error_ref,event_type)
        return False,error_ref
    try:db.resolve_transient_incidents()
    except sqlite3.OperationalError:pass  # Legacy/test databases may predate incident migration.
    db.set_system_state("last_admin_notification",event_type)
    db.set_system_state(f"last_route_success:{event_type}",db.utc_now())
    db.record_audit(None,"routed_delivery_succeeded","notification",target_telegram_id=target_telegram_id,
        related_request_id=related_request_id,related_submission_id=related_submission_id,new_value={"event":event_type})
    return True,None


def routing_summary(config):
    return [(event,*destination(config,event)) for event in ROUTES]
