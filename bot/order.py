"""
VAD Coffee Lounge — full ordering conversation flow.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
)

from config import (
    BARISTAS, SIZES, ROASTS, FLAVORS, BAKERY,
    STATE_BARISTAS, STATE_SIZE, STATE_ROAST,
    STATE_FLAVORS, STATE_BAKERY, STATE_CAFFEINE, STATE_RECEIPT,
)
from receipt import calculate_total, format_receipt

logger = logging.getLogger(__name__)


# ── Order state helpers ────────────────────────────────────────────────────

def _order(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    if "order" not in ctx.user_data:
        ctx.user_data["order"] = {
            "baristas": [], "size": None, "roast": None,
            "flavors": [], "bakery": [], "caffeine": None,
        }
    return ctx.user_data["order"]


def _clear(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.user_data.pop("order", None)


# ── Keyboard builders ──────────────────────────────────────────────────────

def _barista_kb(selected: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(BARISTAS), 3):
        chunk = BARISTAS[i:i + 3]
        rows.append([
            InlineKeyboardButton(
                f"✅ {name}" if name in selected else name,
                callback_data=f"barista:{name}",
            )
            for name in chunk
        ])
    if len(selected) >= 2:
        rows.append([InlineKeyboardButton("✅ Done — Continue →", callback_data="baristas_done")])
    return InlineKeyboardMarkup(rows)


def _size_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(s["label"], callback_data=f"size:{key}")
        for key, s in SIZES.items()
    ]])


def _roast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(r["label"], callback_data=f"roast:{key}")
        for key, r in ROASTS.items()
    ]])


def _flavor_kb(selected: list) -> InlineKeyboardMarkup:
    items = list(FLAVORS.items())
    rows = [
        [
            InlineKeyboardButton(
                f"✅ {v['label']}" if k in selected else v["label"],
                callback_data=f"flavor:{k}",
            )
            for k, v in items[i:i + 2]
        ]
        for i in range(0, len(items), 2)
    ]
    rows.append([
        InlineKeyboardButton("✅ Done", callback_data="flavors_done"),
        InlineKeyboardButton("Skip →",  callback_data="flavors_skip"),
    ])
    return InlineKeyboardMarkup(rows)


def _bakery_kb(selected: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{'✅ ' if k in selected else ''}{v['label']} ({v['duration']})",
            callback_data=f"bakery:{k}",
        )]
        for k, v in BAKERY.items()
    ]
    rows.append([
        InlineKeyboardButton("✅ Done", callback_data="bakery_done"),
        InlineKeyboardButton("Skip →",  callback_data="bakery_skip"),
    ])
    return InlineKeyboardMarkup(rows)


def _caffeine_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⚡ Yes  (+$30 each)", callback_data="caffeine:yes"),
        InlineKeyboardButton("No",                  callback_data="caffeine:no"),
    ]])


def _receipt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤  Submit Order", callback_data="submit")],
        [InlineKeyboardButton("❌  Cancel",        callback_data="cancel")],
    ])


# ── Step text builders ─────────────────────────────────────────────────────

HDR = "☕ <b>VAD Coffee Lounge</b>\n\n"


def _barista_text(selected: list) -> str:
    note = f"\n<i>Selected ({len(selected)}): {', '.join(selected)}</i>" if selected else ""
    return (
        HDR + "<b>Step 1 of 6 — Choose Your Baristas</b>\n"
        "Select at least 2, then tap <b>Done ✅</b>" + note
    )


def _size_text() -> str:
    lines = "\n".join(
        f"  • <b>{s['label']}</b> — {s['duration']} — ${s['price']} each"
        for s in SIZES.values()
    )
    return HDR + "<b>Step 2 of 6 — Choose Your Size</b>\n\n" + lines


def _roast_text() -> str:
    lines = "\n".join(
        f"  • <b>{r['label']}</b> — ${r['price']} each"
        for r in ROASTS.values()
    )
    return HDR + "<b>Step 3 of 6 — Choose Your Roast</b>\n\n" + lines


def _flavor_text(selected: list) -> str:
    note = f"\n<i>Selected: {', '.join(FLAVORS[f]['label'] for f in selected)}</i>" if selected else ""
    return (
        HDR + "<b>Step 4 of 6 — Flavor Shots</b>\n"
        "Vanilla, Caramel, Hazelnut are free · Cinnamon +$15 each" + note
    )


def _bakery_text(selected: list) -> str:
    note = f"\n<i>Selected: {', '.join(BAKERY[b]['label'] for b in selected)}</i>" if selected else ""
    lines = "\n".join(
        f"  • <b>{v['label']}</b> ({v['duration']}) — ${v['price']} each"
        for v in BAKERY.values()
    )
    return HDR + "<b>Step 5 of 6 — Bakery Menu</b> (optional)\n\n" + lines + note


def _caffeine_text() -> str:
    return HDR + "<b>Step 6 of 6 — Caffeine Shot?</b>\n+$30 per barista"


# ── Handlers ───────────────────────────────────────────────────────────────

async def start_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: /start"""
    _clear(ctx)
    order = _order(ctx)
    await update.message.reply_html(
        "☕ <b>Welcome to VAD Coffee Lounge!</b>\n\n"
        "I'll guide you through your order step by step.\n\n"
        "<b>Step 1 of 6 — Choose Your Baristas</b>\n"
        "Select at least 2, then tap <b>Done ✅</b>",
        reply_markup=_barista_kb(order["baristas"]),
    )
    return STATE_BARISTAS


async def toggle_barista(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    name = q.data.split(":", 1)[1]
    baristas = _order(ctx)["baristas"]
    if name in baristas:
        baristas.remove(name)
    else:
        baristas.append(name)
    await q.edit_message_text(_barista_text(baristas), parse_mode="HTML",
                               reply_markup=_barista_kb(baristas))
    return STATE_BARISTAS


async def baristas_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    baristas = _order(ctx)["baristas"]
    if len(baristas) < 2:
        await q.answer("Please select at least 2 baristas.", show_alert=True)
        return STATE_BARISTAS
    await q.answer()
    await q.edit_message_text(_size_text(), parse_mode="HTML", reply_markup=_size_kb())
    return STATE_SIZE


async def choose_size(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _order(ctx)["size"] = q.data.split(":", 1)[1]
    await q.edit_message_text(_roast_text(), parse_mode="HTML", reply_markup=_roast_kb())
    return STATE_ROAST


async def choose_roast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _order(ctx)["roast"] = q.data.split(":", 1)[1]
    order = _order(ctx)
    await q.edit_message_text(_flavor_text(order["flavors"]), parse_mode="HTML",
                               reply_markup=_flavor_kb(order["flavors"]))
    return STATE_FLAVORS


async def toggle_flavor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    flavors = _order(ctx)["flavors"]
    if key in flavors:
        flavors.remove(key)
    else:
        flavors.append(key)
    await q.edit_message_text(_flavor_text(flavors), parse_mode="HTML",
                               reply_markup=_flavor_kb(flavors))
    return STATE_FLAVORS


async def flavors_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    order = _order(ctx)
    await q.edit_message_text(_bakery_text(order["bakery"]), parse_mode="HTML",
                               reply_markup=_bakery_kb(order["bakery"]))
    return STATE_BAKERY


async def toggle_bakery(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    items = _order(ctx)["bakery"]
    if key in items:
        items.remove(key)
    else:
        items.append(key)
    await q.edit_message_text(_bakery_text(items), parse_mode="HTML",
                               reply_markup=_bakery_kb(items))
    return STATE_BAKERY


async def bakery_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(_caffeine_text(), parse_mode="HTML", reply_markup=_caffeine_kb())
    return STATE_CAFFEINE


async def choose_caffeine(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _order(ctx)["caffeine"] = q.data.split(":", 1)[1]
    order = _order(ctx)
    total = calculate_total(order)
    await q.edit_message_text(format_receipt(order, total), parse_mode="HTML",
                               reply_markup=_receipt_kb())
    return STATE_RECEIPT


async def submit_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    order = _order(ctx)

    # Defensive guard — all required fields must be present before we build the receipt
    if len(order["baristas"]) < 2 or not order["size"] or not order["roast"] or order["caffeine"] is None:
        await q.answer("Order is incomplete. Please start over.", show_alert=True)
        _clear(ctx)
        await q.edit_message_text("⚠️ Incomplete order. Type /start to begin again.")
        return ConversationHandler.END

    await q.answer("Submitting…")
    total = calculate_total(order)
    receipt = format_receipt(order, total)

    admin_chat_id = ctx.bot_data.get("admin_chat_id")

    if admin_chat_id:
        user = update.effective_user
        admin_msg = (
            f"🔔 <b>New Order</b> from {user.full_name}"
            + (f" (@{user.username})" if user.username else "")
            + f" — ID: <code>{user.id}</code>\n\n"
            + receipt
        )
        try:
            await ctx.bot.send_message(admin_chat_id, admin_msg, parse_mode="HTML")
            confirmation = "\n\n✅ <b>Order submitted!</b> See you soon. ☕"
        except Exception as exc:
            logger.error("Could not forward order to admin: %s", exc)
            confirmation = "\n\n⚠️ Order saved locally but couldn't reach admin — we'll be in touch!"
    else:
        confirmation = (
            "\n\n✅ <b>Order received!</b>\n"
            "<i>Admin group not connected yet — your order is noted. ☕</i>"
        )

    await q.edit_message_text(receipt + confirmation, parse_mode="HTML")
    _clear(ctx)
    return ConversationHandler.END


async def cancel_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _clear(ctx)
    await q.edit_message_text("❌ Order cancelled. Type /start to begin a new order.")
    return ConversationHandler.END


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(ctx)
    await update.message.reply_text("❌ Order cancelled. Type /start to begin a new order.")
    return ConversationHandler.END


# ── Conversation handler factory ───────────────────────────────────────────

def build_order_conversation() -> ConversationHandler:
    # per_message=False: conversation is tracked per user+chat (one active order per user).
    # The receipt keyboard is always a single message, so per-message routing is not needed.
    return ConversationHandler(
        entry_points=[CommandHandler("start", start_order)],
        per_message=False,
        states={
            STATE_BARISTAS: [
                CallbackQueryHandler(toggle_barista, pattern=r"^barista:"),
                CallbackQueryHandler(baristas_done,  pattern=r"^baristas_done$"),
            ],
            STATE_SIZE: [
                CallbackQueryHandler(choose_size, pattern=r"^size:"),
            ],
            STATE_ROAST: [
                CallbackQueryHandler(choose_roast, pattern=r"^roast:"),
            ],
            STATE_FLAVORS: [
                CallbackQueryHandler(toggle_flavor, pattern=r"^flavor:"),
                CallbackQueryHandler(flavors_next,  pattern=r"^flavors_(done|skip)$"),
            ],
            STATE_BAKERY: [
                CallbackQueryHandler(toggle_bakery, pattern=r"^bakery:"),
                CallbackQueryHandler(bakery_next,   pattern=r"^bakery_(done|skip)$"),
            ],
            STATE_CAFFEINE: [
                CallbackQueryHandler(choose_caffeine, pattern=r"^caffeine:"),
            ],
            STATE_RECEIPT: [
                CallbackQueryHandler(submit_order,  pattern=r"^submit$"),
                CallbackQueryHandler(cancel_order,  pattern=r"^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
        name="order_conversation",
    )
