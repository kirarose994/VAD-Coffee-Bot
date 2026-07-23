"""Read-only MTProto scanner for narrowly bounded Thursday POP dry runs.

This module deliberately has no database or Bot API imports. Raw Telegram content is
used only long enough to apply the existing adapter-neutral classifier and is never
returned, persisted, or logged.
"""

from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import Any, Callable, Mapping

from recovery_contract import AdapterMessage, MediaIndicators, classify_message


FEATURE_FLAG = "TELEGRAM_POP_HISTORY_SCAN_ENABLED"
_URL_SHAPE = re.compile(
    r"(?i)(?:https?://|www\.|t\.me/|telegram\.me/|instagram\.com/|facebook\.com/|x\.com/)"
)


class ScanValidationError(ValueError):
    """Raised before connecting when the requested scan is unsafe or incomplete."""


class ScanScopeError(RuntimeError):
    """Raised if Telegram resolves or returns a chat outside the configured scope."""


def _integer(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None


def _ids(value: str | None) -> frozenset[int]:
    result = set()
    for item in (value or "").split(","):
        parsed = _integer(item)
        if parsed is not None:
            result.add(parsed)
    return frozenset(result)


@dataclass(frozen=True)
class PopHistoryScanConfig:
    """Secret-safe, disabled-by-default configuration for the standalone scanner."""

    enabled: bool = False
    api_id: int | None = None
    api_hash: str | None = field(default=None, repr=False)
    session_string: str | None = field(default=None, repr=False)
    pop_chat_id: int | None = None
    pop_thread_id: int | None = None
    owner_user_ids: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PopHistoryScanConfig":
        values = os.environ if environ is None else environ
        enabled = values.get(FEATURE_FLAG, "false").strip().casefold() in {
            "1", "true", "yes", "on",
        }
        return cls(
            enabled=enabled,
            api_id=_integer(values.get("TELEGRAM_API_ID")),
            api_hash=(values.get("TELEGRAM_API_HASH") or "").strip() or None,
            session_string=(values.get("TELEGRAM_SESSION_STRING") or "").strip() or None,
            pop_chat_id=_integer(values.get("POP_CHAT_ID")),
            pop_thread_id=_integer(values.get("POP_THREAD_ID")),
            owner_user_ids=_ids(",".join(filter(None, (
                values.get("OWNER_USER_IDS", ""), values.get("OWNER_TELEGRAM_IDS", ""),
            )))),
        )

    def validate(self, owner_id: int) -> None:
        if not self.enabled:
            raise ScanValidationError(f"{FEATURE_FLAG} must be enabled")
        missing = []
        if not self.api_id or self.api_id <= 0:
            missing.append("TELEGRAM_API_ID")
        if not self.api_hash:
            missing.append("TELEGRAM_API_HASH")
        if not self.session_string:
            missing.append("TELEGRAM_SESSION_STRING")
        if self.pop_chat_id is None or self.pop_chat_id >= 0:
            missing.append("POP_CHAT_ID")
        if self.pop_thread_id is None or self.pop_thread_id <= 0:
            missing.append("POP_THREAD_ID")
        if missing:
            raise ScanValidationError("Missing required configuration: " + ", ".join(missing))
        if owner_id not in self.owner_user_ids:
            raise ScanValidationError("The supplied operator is not a configured Owner")


def validate_window(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ScanValidationError("Start and end must include timezone offsets")
    if start > end:
        raise ScanValidationError("Start must be earlier than or equal to end")


def _thread_id(message: Any) -> int | None:
    explicit = getattr(message, "message_thread_id", None)
    if explicit is not None:
        return int(explicit)
    reply = getattr(message, "reply_to", None)
    if not reply:
        return None
    top = getattr(reply, "reply_to_top_id", None)
    if top is not None:
        return int(top)
    if getattr(reply, "forum_topic", False):
        root = getattr(reply, "reply_to_msg_id", None)
        return int(root) if root is not None else None
    return None


def _has_url_entity(message: Any) -> bool:
    return any(type(entity).__name__.casefold() in {
        "messageentityurl", "messageentitytexturl",
    } for entity in (getattr(message, "entities", None) or ()))


def _media(message: Any) -> MediaIndicators:
    # Telethon represents a forwarded Story as MessageMediaStory. The scanner
    # keeps only this type indicator, never Story content.
    forwarded_story = type(getattr(message, "media", None)).__name__ == "MessageMediaStory"
    photo = bool(getattr(message, "photo", None))
    voice = bool(getattr(message, "voice", None))
    audio = bool(getattr(message, "audio", None)) and not voice
    video = bool(getattr(message, "video", None))
    animation = bool(getattr(message, "gif", None) or getattr(message, "animation", None))
    sticker = bool(getattr(message, "sticker", None))
    raw_document = getattr(message, "document", None)
    document = bool(raw_document) and not any((voice, audio, video, animation, sticker))
    mime_type = getattr(raw_document, "mime_type", None) if raw_document else None
    extension = None
    file_value = getattr(message, "file", None)
    file_name = getattr(file_value, "name", None)
    if document and file_name:
        extension = PurePath(str(file_name)).suffix or None
    duration = getattr(file_value, "duration", None)
    try:
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    return MediaIndicators(
        photo=photo, document=document, document_mime_type=mime_type,
        document_extension=extension, animation=animation, video=video,
        voice=voice, audio=audio, sticker=sticker, forwarded_story=forwarded_story,
        has_url_entity=_has_url_entity(message), duration_seconds=duration,
    )


def _default_client(config: PopHistoryScanConfig):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(config.session_string), config.api_id, config.api_hash,
        receive_updates=False, catch_up=False)


def _default_peer_id(entity: Any) -> int:
    from telethon.utils import get_peer_id

    return int(get_peer_id(entity))


async def scan_pop_history(
    config: PopHistoryScanConfig,
    *, owner_id: int, start: datetime, end: datetime,
    client_factory: Callable[[PopHistoryScanConfig], Any] | None = None,
    peer_id_resolver: Callable[[Any], int] | None = None,
) -> dict[str, Any]:
    """Connect once and return a privacy-minimal dry-run report without writes."""

    config.validate(owner_id)
    validate_window(start, end)
    factory = client_factory or _default_client
    resolver = peer_id_resolver or _default_peer_id
    client = factory(config)
    if inspect.isawaitable(client):
        client = await client
    ignored = {reason: 0 for reason in (
        "outside_window", "wrong_topic", "duplicate_message",
        "missing_sender", "unqualified_evidence",
    )}
    rows: list[dict[str, Any]] = []
    senders: set[int] = set()
    seen: set[int] = set()
    examined = 0
    connected = False
    try:
        await client.connect()
        connected = True
        if not await client.is_user_authorized():
            raise ScanValidationError("TELEGRAM_SESSION_STRING is not authorized")
        entity = await client.get_entity(config.pop_chat_id)
        resolved_chat_id = int(resolver(entity))
        if resolved_chat_id != config.pop_chat_id:
            raise ScanScopeError("Configured POP chat resolved to a different Telegram peer")
        if getattr(entity, "megagroup", None) is False or getattr(entity, "forum", None) is False:
            raise ScanScopeError("Configured POP chat is not a forum supergroup")
        async for message in client.iter_messages(
            entity, offset_date=end + timedelta(microseconds=1),
            reply_to=config.pop_thread_id,
        ):
            examined += 1
            source_at = getattr(message, "date", None)
            if source_at is None or source_at.tzinfo is None or source_at > end:
                ignored["outside_window"] += 1
                continue
            if source_at < start:
                ignored["outside_window"] += 1
                break
            message_chat_id = getattr(message, "chat_id", resolved_chat_id)
            if message_chat_id != config.pop_chat_id:
                raise ScanScopeError("Telegram returned a message outside the configured POP chat")
            if _thread_id(message) != config.pop_thread_id:
                ignored["wrong_topic"] += 1
                continue
            message_id = int(getattr(message, "id"))
            if message_id in seen:
                ignored["duplicate_message"] += 1
                continue
            seen.add(message_id)
            sender_id = getattr(message, "sender_id", None)
            if sender_id is None:
                ignored["missing_sender"] += 1
                continue
            sender_id = int(sender_id)
            media = _media(message)
            body = (getattr(message, "message", None) or "").strip()
            has_caption = bool(body and media.any_media)
            has_text = bool(body and not media.any_media)
            envelope = classify_message(AdapterMessage(
                canonical_chat_id=config.pop_chat_id, message_id=message_id,
                thread_id=config.pop_thread_id, sender_telegram_id=sender_id,
                original_timestamp=source_at, edit_timestamp=getattr(message, "edit_date", None),
                text=body if has_text else None, caption=body if has_caption else None,
                media=media,
            ))
            if envelope.derived.pop_decision == "unqualified":
                ignored["unqualified_evidence"] += 1
            senders.add(sender_id)
            proof_type = envelope.derived.pop_proof_type
            rows.append({
                "message_id": message_id,
                "sender_telegram_id": sender_id,
                "original_timestamp": source_at.isoformat(),
                "edit_timestamp": envelope.edit_timestamp.isoformat() if envelope.edit_timestamp else None,
                "media_type": envelope.message_type,
                "has_text": has_text,
                "has_caption": has_caption,
                "has_link": bool(media.has_url_entity or _URL_SHAPE.search(body)),
                "qualified_media": proof_type in {
                    "photo", "image_document", "animation", "video", "voice", "audio",
                    "forwarded_story",
                },
                "ambiguous_evidence": envelope.derived.pop_decision == "needs_review",
                "pop_decision": envelope.derived.pop_decision,
                "pop_proof_type": proof_type,
                "pop_reason": envelope.derived.pop_reason,
            })
    finally:
        if connected:
            await client.disconnect()
    return {
        "dry_run": True, "read_only": True,
        "configured_chat_id": config.pop_chat_id,
        "configured_thread_id": config.pop_thread_id,
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "total_messages_examined": examined, "total_messages_found": len(rows),
        "unique_creator_telegram_ids": sorted(senders),
        "messages": rows, "ignored_message_counts": ignored,
    }
