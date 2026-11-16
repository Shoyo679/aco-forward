"""Read checkout webhooks (Valor, Shikari, sniped.gg, Refract) and find the customer tag in the profile name.

A message comes in as a plain dict (see bot.message_record):
    {"id", "ts", "channel_id", "guild_id", "source_name", "jump_url", "embeds": [embed dict]}
Only what ACO Forward needs is kept. Emails, proxies, addresses and card details are never copied. The order number
is kept for the runner's own Checkouts tab (owner, Nov 16 2026), plus a one-way code (order_fp) to match later
cancel messages; it is never posted in Discord or sent to a customer.

Stellar is listed by the owner but its webhook layout isn't known yet. It is not guessed: until a real Stellar
test webhook is added here (with a test), its messages are counted under "Other senders" like any other bot.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import re

BOTS = {"valor": "Valor", "shikari": "Shikari", "sniped": "sniped.gg", "refract": "Refract"}
PENDING_BOTS = {"stellar": "Stellar"}   # asked for, waiting for a real test webhook

TEST_MARKERS = ("this is a test message from valor",
                "your webhook is configured and working correctly")   # Shikari "Bing Bong"

USERNAME = re.compile(r"^[a-z0-9_.]{2,32}$")   # Discord usernames: lowercase letters, digits, _ and .


def _unspoil(value: str) -> str:
    return value.replace("||", "").strip()


def fields_of(embed: dict) -> dict[str, str]:
    return {f.get("name", ""): _unspoil(f.get("value", "")) for f in embed.get("fields", [])}


def detect_bot(record: dict, embed: dict) -> str | None:
    if (embed.get("author") or {}).get("name") == "Shikari":
        return "shikari"
    footer = (embed.get("footer") or {}).get("text", "")
    if footer.startswith("Prism Technologies"):   # Refract (by Prism)
        return "refract"
    if footer.startswith("Valor") or record.get("source_name", "").startswith("Valor"):
        return "valor"
    if footer == "sniped.gg" or record.get("source_name") == "sniped.gg":
        return "sniped"
    return None


def is_test(embed: dict) -> bool:
    text = f"{embed.get('title', '')} {embed.get('description', '')}".lower()
    if (embed.get("author") or {}).get("name", "").strip().lower().endswith("| refract"):
        return True
    if (embed.get("title") or "").strip().lower() == "webhook test" and not embed.get("fields"):
        return True
    return any(m in text for m in TEST_MARKERS)


def title_of(bot: str | None, embed: dict) -> str:
    raw = (embed.get("author") or {}).get("name", "").split("|")[0] if bot == "refract" else embed.get("title", "")
    return re.sub(r":[a-z0-9_+-]+:", "", raw or "").strip()


def kind_of(bot: str, title: str) -> str:
    """success / cancel / other (declines, errors, raffles, "still good"...). A cancel (Valor's order checker
    "Order Canceled!", Shikari "Order Canceled: ...", sniped.gg "Cancelled Checkout") takes back the checkout with
    the same order number, so it isn't charged."""
    t = title.lower()
    if "cancel" in t:
        return "cancel"
    if "review hold" in t or "checked out" in t or "successful checkout" in t:
        return "success"
    return "other"


def _clean(value: str | None) -> str | None:
    return html.unescape(value).strip() or None if value else None


def _price(value: str | None) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", (value or "").replace(",", ""))
    return (float(m.group()) or None) if m else None


def _qty(value: str | None) -> int:
    m = re.search(r"\d+", value or "")
    return max(1, int(m.group())) if m else 1


PLACEHOLDERS = {"", "—", "-", "UNKNOWN", "N/A"}


def _store(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s*\(.*?\)\s*$", "", value)
    return re.sub(r"\s+US$", "", value).strip() or None


def _id_from_url(url: str) -> str | None:
    m = re.search(r"/A-(\d+)", url) or re.search(r"/ip/(?:[^/]*/)?(\d+)", url)
    return m.group(1) if m else None


def _product(bot: str, embed: dict, fields: dict) -> tuple[str | None, str | None]:
    if bot == "shikari":
        m = re.search(r"\[\*\*(.+?)\*\*\]\((\S+?)\)", embed.get("description", ""))
        return (_id_from_url(m.group(2)), _clean(m.group(1))) if m else (None, None)
    product = fields.get("Product") or ""
    if bot in ("valor", "refract"):
        m = re.match(r"\[(?:\((\S+)\)\s*)?(.+?)\]\((\S+?)\)", product)
        if m:
            return m.group(1) or _id_from_url(m.group(3)), _clean(m.group(2))
    sku = fields.get("SKU", "")
    return (None if sku in PLACEHOLDERS else sku), (None if product in PLACEHOLDERS else _clean(product))


def tag_of(profile: str | None) -> tuple[str | None, str | None]:
    """Profile name -> (tag, problem). The tag is the text before the first space, lower-cased:
    "zeyrox0p 1cxd" -> "zeyrox0p". problem says why a name can't be a tag (shown as a warning)."""
    if not profile:
        return None, "No profile name in the webhook"
    first = profile.split()[0].lower()
    if not USERNAME.match(first):
        return None, "Doesn't start with a Discord username"
    return first, None


def order_fp(order_number: str | None, key: bytes) -> str | None:
    """One-way code of an order number (the number itself is never saved)."""
    if not order_number or order_number in PLACEHOLDERS:
        return None
    return hmac.new(key, order_number.strip().encode(), hashlib.sha256).hexdigest()[:24]


def parse(record: dict, key: bytes) -> dict | None:
    """A message -> {"kind": "success" | "cancel" | "other" | "test" | "unknown_sender", ...} or None (no embed)."""
    if not record.get("embeds"):
        return None
    embed = record["embeds"][0]
    bot = detect_bot(record, embed)
    if bot is None:
        return {"kind": "unknown_sender", "sender": (record.get("source_name") or "?")[:80]}
    if is_test(embed):
        return {"kind": "test", "bot": bot}
    fields = fields_of(embed)
    title = title_of(bot, embed)
    kind = kind_of(bot, title)
    if kind == "other" or not fields:
        return {"kind": "other", "bot": bot, "title": title[:80]}
    raw_order = fields.get("Order Number") or fields.get("Order ID")
    order = order_fp(raw_order, key)
    if kind == "cancel":
        return {"kind": "cancel", "bot": bot, "order_fp": order}
    pid, name = _product(bot, embed, fields)
    qty = _qty(fields.get("Quantity") or fields.get("Qty"))
    price = _price(fields.get("Price"))
    if price is not None and bot == "valor" and qty > 1:   # Valor's Price is the whole order
        price = round(price / qty, 2)
    profile = next(iter((fields.get("Profile") or "").splitlines()), "").strip() or None   # sniped: line 2 = email
    tag, problem = tag_of(profile)
    image = (embed.get("thumbnail") or {}).get("url") or (embed.get("image") or {}).get("url")
    return {
        "kind": "success", "bot": bot,
        "store": _store(fields.get("Site") or fields.get("Store") or (
            (embed.get("author") or {}).get("name", "").split("|", 1)[1].strip()
            if bot == "refract" and "|" in (embed.get("author") or {}).get("name", "") else None)),
        "product_id": pid, "product_name": name or "Unknown product",
        "product_key": (pid or (name or "unknown").lower()).strip(),
        "price": price, "qty": qty,
        "profile": profile[:100] if profile else None, "tag": tag, "problem": problem,
        "order_fp": order,
        "order_number": raw_order.strip()[:80] if raw_order and raw_order not in PLACEHOLDERS else None,
        "image": image if image and image.startswith("https://") else None,
    }
