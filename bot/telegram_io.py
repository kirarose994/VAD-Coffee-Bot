"""Bounded retry policy for transient Telegram transport failures."""

import asyncio

import httpcore
import httpx
from telegram.error import NetworkError


TRANSIENT_NETWORK_ERRORS=(httpcore.ReadError,httpx.ReadError,NetworkError)


def is_transient_network_error(error):
    """Recognize direct and wrapped Telegram/httpx read failures."""
    seen=set();current=error
    while current is not None and id(current) not in seen:
        if isinstance(current,TRANSIENT_NETWORK_ERRORS):return True
        seen.add(id(current));current=current.__cause__ or current.__context__
    return False


def transient_root_type(error):
    """Return a stable root transport type for operation-specific fingerprints."""
    seen=set();current=error;matched=None
    while current is not None and id(current) not in seen:
        if isinstance(current,(httpcore.ReadError,httpx.ReadError)):matched="ReadError"
        elif matched is None and isinstance(current,NetworkError):matched=type(current).__name__
        seen.add(id(current));current=current.__cause__ or current.__context__
    return matched


async def retry_telegram(operation,*,attempts=3,base_delay=0.25,sleep=asyncio.sleep):
    """Retry only transient network reads using bounded exponential backoff."""
    for attempt in range(attempts):
        try:return await operation()
        except Exception as error:
            if not is_transient_network_error(error) or attempt+1>=attempts:raise
            await sleep(base_delay*(2**attempt))
