"""Privacy-safe POP proof classification without fetching submitted URLs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


_URL_CANDIDATE = re.compile(
    r"(?i)(?<![\w@])(?:https?://|www\.|t\.me/|telegram\.me/|instagram\.com/|facebook\.com/|x\.com/)[^\s<>{}\[\]]+"
)
_MEDIA_WITH_CAPTION = ("animation", "video", "voice", "audio")
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_POSTING_ACTION = re.compile(r"\b(?:posted|shared|published|uploaded|added|put|sent)\b",re.I)
_PROOF_SUBJECT = re.compile(r"\b(?:weekly\s+pop|pop|flyer|promo(?:tion)?|advert(?:isement)?)\b",re.I)
_DESTINATION = re.compile(r"\b(?:story|channel|page|feed|timeline|group|telegram|instagram|facebook|reddit|twitter|website|site)\b",re.I)
_PROOF_HINT = re.compile(r"\b(?:post(?:ed)?|share(?:d)?|flyer|weekly\s+pop|promo|story|channel)\b",re.I)


@dataclass(frozen=True)
class PopProofDecision:
    proof_type: str | None
    needs_review: bool = False
    reason: str = "unqualified"


def _entity_type(entity) -> str:
    value = getattr(entity, "type", "")
    return str(getattr(value, "value", value)).casefold()


def _valid_url(value: str | None) -> bool:
    """Validate syntax only; never open, fetch, resolve, or retain the URL."""
    candidate = (value or "").strip().rstrip(".,;:!?)]}'\"")
    if not candidate:
        return False
    if candidate.casefold().startswith(("www.","t.me/","telegram.me/","instagram.com/","facebook.com/","x.com/")):
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


def classify_pop_candidate(message) -> PopProofDecision:
    """Classify proof without opening links or retaining submitted content."""
    if getattr(message, "photo", None):
        return PopProofDecision("photo",reason="photo")
    document=getattr(message,"document",None)
    filename=str(getattr(document,"file_name","")).casefold() if document else ""
    if document and (getattr(document,"mime_type",None) in _IMAGE_MIME_TYPES or
                     str(getattr(document,"mime_type","")).casefold().startswith("image/") or
                     filename.endswith((".jpg",".jpeg",".png",".webp",".gif"))):
        return PopProofDecision("image_document",reason="image_document")
    has_url = message_has_url(message)
    caption = (getattr(message, "caption", None) or "").strip()
    for kind in _MEDIA_WITH_CAPTION:
        if getattr(message, kind, None) and (caption or has_url):
            return PopProofDecision(kind,reason="captioned_media")
    if has_url:
        return PopProofDecision("link",reason="validated_link")
    text=(getattr(message,"text",None) or caption).strip()
    if text and _POSTING_ACTION.search(text) and _PROOF_SUBJECT.search(text) and _DESTINATION.search(text):
        return PopProofDecision("text",reason="clear_text_proof")
    if text and _PROOF_HINT.search(text):
        return PopProofDecision(None,needs_review=True,reason="ambiguous_text")
    return PopProofDecision(None,reason="unqualified_text")


def classify_pop_proof(message) -> str | None:
    """Compatibility wrapper returning only an automatically usable proof type."""
    return classify_pop_candidate(message).proof_type
