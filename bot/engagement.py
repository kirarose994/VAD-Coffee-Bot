"""Deterministic meaningful-engagement classification."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

GREETINGS = {"hi","hey","hello","hiya","morning","good morning","good afternoon","good evening","gm","gn","howdy"}
PROMO = re.compile(r"(?:https?://|www\.|t\.me/|onlyfans|subscribe|promo\s*code|discount|dm\s+me|buy\s+now)", re.I)
WORD = re.compile(r"[\w']+", re.UNICODE)


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    normalized: str = ""
    digest: str = ""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return " ".join(text.split())


def classify(text, *, media=False, is_repeat=lambda digest, since: False, now=None) -> Decision:
    if media or text is None:
        return Decision(False, "non_text")
    normalized = normalize(text)
    words = WORD.findall(normalized)
    if not words:
        return Decision(False, "emoji_or_punctuation_only", normalized)
    if normalized.strip("!.,? ") in GREETINGS or " ".join(words) in GREETINGS:
        return Decision(False, "greeting_only", normalized)
    if PROMO.search(normalized):
        return Decision(False, "promotional_spam", normalized)
    if len(words) < 3 or len("".join(words)) < 12:
        return Decision(False, "too_short", normalized)
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    since = (now or datetime.now(timezone.utc)) - timedelta(days=7)
    if is_repeat(digest, since.isoformat()):
        return Decision(False, "repeated_text", normalized, digest)
    return Decision(True, "meaningful", normalized, digest)
