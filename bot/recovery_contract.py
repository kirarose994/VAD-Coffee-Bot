"""Adapter-neutral, non-persistent message classification for future recovery."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from types import SimpleNamespace

from engagement import Decision, classify as classify_participation
from engagement import contains_promotional_spam, normalize
from pop_reliability import classify_pop_candidate


HISTORY_RECOVERY_LEASE_NAME = "telegram_mtproto_history_recovery"
CLASSIFICATION_VERSION = "bot-api-parity-v1"
MIN_AUDIO_PARTICIPATION_SECONDS = 5


@dataclass(frozen=True)
class MediaIndicators:
    """Minimal media facts needed by existing classifiers; never media content."""

    photo: bool = False
    document: bool = False
    document_mime_type: str | None = None
    document_extension: str | None = None
    animation: bool = False
    video: bool = False
    voice: bool = False
    audio: bool = False
    sticker: bool = False
    forwarded_story: bool = False
    has_url_entity: bool = False
    duration_seconds: int | None = None
    identity_hash: str | None = None

    def __post_init__(self):
        extension = self.document_extension
        if extension:
            extension = PurePath(f"file{extension if extension.startswith('.') else '.' + extension}").suffix.casefold()
            object.__setattr__(self, "document_extension", extension)
        if self.document_mime_type:
            object.__setattr__(self, "document_mime_type", self.document_mime_type.casefold())
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("Media duration cannot be negative")
        if self.identity_hash is not None and len(self.identity_hash) != 64:
            raise ValueError("Media identity must be a SHA-256 digest")

    @property
    def any_media(self) -> bool:
        return any((self.photo, self.document, self.animation, self.video,
                    self.voice, self.audio, self.sticker, self.forwarded_story))


@dataclass(frozen=True)
class AdapterMessage:
    """Ephemeral adapter input. Raw text is intentionally absent from the output envelope."""

    canonical_chat_id: int
    message_id: int
    sender_telegram_id: int
    original_timestamp: datetime
    thread_id: int | None = None
    edit_timestamp: datetime | None = None
    text: str | None = None
    caption: str | None = None
    media: MediaIndicators = field(default_factory=MediaIndicators)

    def __post_init__(self):
        if not all(isinstance(value, int) for value in
                   (self.canonical_chat_id, self.message_id, self.sender_telegram_id)):
            raise TypeError("Canonical chat, message, and sender IDs must be integers")
        if self.message_id <= 0:
            raise ValueError("Telegram message ID must be positive")
        for name, value in (("original_timestamp", self.original_timestamp),
                            ("edit_timestamp", self.edit_timestamp)):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class DerivedClassification:
    participation_decision: str
    participation_reason: str
    participation_digest: str | None
    pop_decision: str
    pop_proof_type: str | None
    pop_reason: str


@dataclass(frozen=True)
class NormalizedMessageEnvelope:
    """Privacy-minimal result safe to persist in a later recovery inbox."""

    canonical_chat_id: int
    message_id: int
    thread_id: int | None
    sender_telegram_id: int
    original_timestamp: datetime
    edit_timestamp: datetime | None
    message_type: str
    media: MediaIndicators
    normalized_text_hash: str | None
    classification_version: str
    derived: DerivedClassification


def _message_type(media: MediaIndicators, text: str | None, caption: str | None) -> str:
    for kind in ("forwarded_story", "photo", "document", "animation", "video", "voice", "audio", "sticker"):
        if getattr(media, kind):
            return kind
    return "text" if text is not None else "caption" if caption is not None else "other"


def _normalized_text_hash(text: str | None, caption: str | None) -> str | None:
    body = normalize("\n".join(value for value in (text, caption) if value))
    return hashlib.sha256(body.encode()).hexdigest() if body else None


def _existing_pop_message(message: AdapterMessage):
    media = message.media
    document = None
    if media.document:
        document = SimpleNamespace(
            mime_type=media.document_mime_type,
            file_name=f"recovery{media.document_extension or ''}",
        )
    entities = (SimpleNamespace(type="url"),) if media.has_url_entity else ()
    return SimpleNamespace(
        text=message.text,
        caption=message.caption,
        entities=entities,
        caption_entities=entities,
        photo=[object()] if media.photo else None,
        document=document,
        animation=object() if media.animation else None,
        video=object() if media.video else None,
        voice=object() if media.voice else None,
        audio=object() if media.audio else None,
        sticker=object() if media.sticker else None,
        story=object() if media.forwarded_story else None,
    )


def _existing_participation_decision(message: AdapterMessage, is_repeat, now,
                                     min_words, min_characters, repeat_window_days):
    media = message.media
    if media.voice or media.audio:
        event_type = "voice_message" if media.voice else "audio_message"
        duration = int(media.duration_seconds or 0)
        digest = media.identity_hash
        if duration < MIN_AUDIO_PARTICIPATION_SECONDS:
            return Decision(False,"audio_too_short",digest=digest or "")
        if contains_promotional_spam(message.caption or ""):
            return Decision(False,"promotional_spam",digest=digest or "")
        if not digest:
            return Decision(False,"audio_missing_file_identity")
        since = (now or datetime.now(timezone.utc))-timedelta(days=int(repeat_window_days))
        if is_repeat(digest,since.isoformat()):
            return Decision(False,"duplicate_audio",digest=digest)
        return Decision(True,event_type,digest=digest)
    return classify_participation(
        message.text,
        media=media.any_media,
        is_repeat=is_repeat,
        now=now,
        min_words=min_words,
        min_characters=min_characters,
        repeat_window_days=repeat_window_days,
    )


def classify_message(message: AdapterMessage, *, is_repeat=lambda digest, since: False,
                     now=None, min_words=3, min_characters=12,
                     repeat_window_days=7) -> NormalizedMessageEnvelope:
    """Apply today's classifiers without changing or wrapping live Bot API handlers."""

    participation = _existing_participation_decision(message,is_repeat,now,
        min_words,min_characters,repeat_window_days)
    pop = classify_pop_candidate(_existing_pop_message(message))
    pop_decision = "qualified" if pop.proof_type else "needs_review" if pop.needs_review else "unqualified"
    return NormalizedMessageEnvelope(
        canonical_chat_id=message.canonical_chat_id,
        message_id=message.message_id,
        thread_id=message.thread_id,
        sender_telegram_id=message.sender_telegram_id,
        original_timestamp=message.original_timestamp,
        edit_timestamp=message.edit_timestamp,
        message_type=_message_type(message.media, message.text, message.caption),
        media=message.media,
        normalized_text_hash=_normalized_text_hash(message.text, message.caption),
        classification_version=CLASSIFICATION_VERSION,
        derived=DerivedClassification(
            participation_decision="accepted" if participation.accepted else "rejected",
            participation_reason=participation.reason,
            participation_digest=participation.digest or None,
            pop_decision=pop_decision,
            pop_proof_type=pop.proof_type,
            pop_reason=pop.reason,
        ),
    )
