"""Privacy-safe POP proof classification without fetching submitted URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_URL_CANDIDATE = re.compile(
    r"(?i)(?<![\w@])(?:https?://|www\.|t\.me/|telegram\.me/)[^\s<>{}\[\]]+"
)
_MEDIA_WITH_CAPTION = ("animation", "video", "voice", "audio")


def _entity_type(entity) -> str:
    value = getattr(entity, "type", "")
    return str(getattr(value, "value", value)).casefold()


def _valid_url(value: str | None) -> bool:
    """Validate syntax only; never open, fetch, resolve, or retain the URL."""
    candidate = (value or "").strip().rstrip(".,;:!?)]}'\"")
    if not candidate:
        return False
    if candidate.casefold().startswith(("www.", "t.me/", "telegram.me/")):
        candidate = "https://" + candidate
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.hostname)


def message_has_url(message) -> bool:
    """Detect Telegram URL entities and safely parsed URL-shaped text."""
    for entities_name in ("entities", "caption_entities"):
        for entity in getattr(message, entities_name, None) or ():
            kind = _entity_type(entity)
            if kind == "text_link" and _valid_url(getattr(entity, "url", None)):
                return True
            if kind == "url":
                # Telegram has already classified the represented text as a URL. We do
                # not extract or store it because entity offsets use UTF-16 code units.
                return True
    body = "\n".join(filter(None, (getattr(message, "text", None), getattr(message, "caption", None))))
    return any(_valid_url(match.group(0)) for match in _URL_CANDIDATE.finditer(body))


def classify_pop_proof(message) -> str | None:
    """Return minimal proof metadata, or None for an unqualified message."""
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "document", None):
        return "document"
    has_url = message_has_url(message)
    caption = (getattr(message, "caption", None) or "").strip()
    for kind in _MEDIA_WITH_CAPTION:
        if getattr(message, kind, None) and (caption or has_url):
            return kind
    if has_url:
        return "link"
    return None
