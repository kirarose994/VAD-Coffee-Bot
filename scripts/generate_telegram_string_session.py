"""Interactively create a Telethon StringSession without writing a session file."""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any


API_ID_PROMPT = "Telegram API ID: "
API_HASH_PROMPT = "Telegram API hash (input hidden): "
PHONE_PROMPT = "Telegram phone number (international format, e.g. +15551234567): "
CODE_PROMPT = "Telegram login code: "
PASSWORD_PROMPT = "Two-step verification password (input hidden, if requested): "


class SessionSetupError(ValueError):
    """Safe configuration error that never includes credential values."""


def _api_id(values: Mapping[str, str], input_fn: Callable[[str], str]) -> int:
    raw = (values.get("TELEGRAM_API_ID") or "").strip() or input_fn(API_ID_PROMPT).strip()
    try:
        result = int(raw)
    except ValueError as exc:
        raise SessionSetupError("Telegram API ID must be a positive integer") from exc
    if result <= 0:
        raise SessionSetupError("Telegram API ID must be a positive integer")
    return result


def _api_hash(values: Mapping[str, str], secret_input_fn: Callable[[str], str]) -> str:
    result = (values.get("TELEGRAM_API_HASH") or "").strip()
    if not result:
        result = secret_input_fn(API_HASH_PROMPT).strip()
    if not result:
        raise SessionSetupError("Telegram API hash is required")
    return result


def _client(api_id: int, api_hash: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(), api_id, api_hash,
        receive_updates=False, catch_up=False)


async def generate_string_session(
    *,
    environ: Mapping[str, str] | None = None,
    input_fn: Callable[[str], str] | None = None,
    secret_input_fn: Callable[[str], str] | None = None,
    client_factory: Callable[[int, str], Any] | None = None,
) -> str:
    """Authorize interactively and return the secret without persisting it."""

    values = os.environ if environ is None else environ
    read = input if input_fn is None else input_fn
    read_secret = getpass.getpass if secret_input_fn is None else secret_input_fn
    api_id = _api_id(values, read)
    api_hash = _api_hash(values, read_secret)
    client = (client_factory or _client)(api_id, api_hash)
    try:
        await client.start(
            phone=lambda: read(PHONE_PROMPT).strip(),
            code_callback=lambda: read(CODE_PROMPT).strip(),
            password=lambda: read_secret(PASSWORD_PROMPT),
        )
        session = client.session.save()
        if not session:
            raise SessionSetupError("Telethon did not return a StringSession")
        return session
    finally:
        await client.disconnect()


async def _main() -> int:
    try:
        session = await generate_string_session()
    except SessionSetupError as exc:
        print(f"Session generation refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Session generation failed safely: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("Session created. Store the following value as a secret; do not share or commit it.")
    print(f"TELEGRAM_SESSION_STRING={session}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
