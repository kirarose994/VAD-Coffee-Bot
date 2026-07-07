"""
Price calculation and receipt formatting for VAD Coffee Lounge Bot.
"""

from config import SIZES, ROASTS, FLAVORS, BAKERY


def calculate_total(order: dict) -> int:
    n = len(order["baristas"])
    total = 0

    if order["size"]:
        total += SIZES[order["size"]]["price"] * n

    if order["roast"]:
        total += ROASTS[order["roast"]]["price"] * n

    for f in order["flavors"]:
        total += FLAVORS[f]["price"] * n  # free flavors add 0

    for b in order["bakery"]:
        total += BAKERY[b]["price"] * n

    if order["caffeine"] == "yes":
        total += 30 * n

    return total


def format_receipt(order: dict, total: int) -> str:
    n = len(order["baristas"])
    baristas_text = ", ".join(order["baristas"])

    size = SIZES[order["size"]]
    roast = ROASTS[order["roast"]]

    # Flavors line
    if order["flavors"]:
        flavor_labels = [FLAVORS[f]["label"] for f in order["flavors"]]
        flavor_cost = sum(FLAVORS[f]["price"] for f in order["flavors"]) * n
        flavor_paid = [FLAVORS[f]["label"] for f in order["flavors"] if FLAVORS[f]["price"] > 0]
        if flavor_paid:
            flavor_line = (
                f"🍬 <b>Flavors:</b> {', '.join(flavor_labels)}"
                f" — +${sum(FLAVORS[f]['price'] for f in order['flavors'] if FLAVORS[f]['price'] > 0)}"
                f" × {n} = <b>${flavor_cost}</b>"
            )
        else:
            flavor_line = f"🍬 <b>Flavors:</b> {', '.join(flavor_labels)} — <b>Free</b>"
    else:
        flavor_line = "🍬 <b>Flavors:</b> None"

    # Bakery lines
    if order["bakery"]:
        bakery_lines = []
        for b in order["bakery"]:
            item = BAKERY[b]
            bakery_lines.append(
                f"   • {item['label']} ({item['duration']}) — ${item['price']} × {n} = <b>${item['price'] * n}</b>"
            )
        bakery_section = "🥐 <b>Bakery:</b>\n" + "\n".join(bakery_lines)
    else:
        bakery_section = "🥐 <b>Bakery:</b> None"

    # Caffeine line
    if order["caffeine"] == "yes":
        caffeine_line = f"⚡ <b>Caffeine Shot:</b> Yes — $30 × {n} = <b>${30 * n}</b>"
    else:
        caffeine_line = "⚡ <b>Caffeine Shot:</b> No"

    return "\n".join([
        "☕ <b>VAD Coffee Lounge — Order Receipt</b>",
        "",
        f"💕 <b>Baristas ({n}):</b> {baristas_text}",
        "",
        f"📏 <b>Size:</b> {size['label']} ({size['duration']}) — ${size['price']} × {n} = <b>${size['price'] * n}</b>",
        f"🫘 <b>Roast:</b> {roast['label']} — ${roast['price']} × {n} = <b>${roast['price'] * n}</b>",
        flavor_line,
        bakery_section,
        caffeine_line,
        "",
        "─" * 22,
        f"💛 <b>Total: ${total:,}</b>",
    ])
