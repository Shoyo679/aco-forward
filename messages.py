"""The customer's DMs, built once here and used both for Discord (bot.py) and for the dashboard preview, so the
preview always matches what is sent. Design B (owner, Nov 16 2026): the total first, then one line per product.

A message is a plain dict: {content, color, title, description, fields: [{name, value}], footer}.
Text uses Discord markdown: **bold**, ~~strike~~, <@id> mentions.
"""
from __future__ import annotations

import time
from datetime import datetime

GREEN, AMBER, RED = 0x23A55A, 0xF0B232, 0xF23F43
FOOTER = "Questions? Reply to your runner"
DAY = 86400


def money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.0f}" if abs(v - round(v)) < 1e-9 else f"${v:,.2f}"


def day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %b %d").replace(" 0", " ")


def clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


def span(first: float, last: float) -> str:
    if datetime.fromtimestamp(first).date() == datetime.fromtimestamp(last).date():
        return f"{clock(first)} – {clock(last)}"
    return f"{clock(first)} – {day(last)}, {clock(last)}"


def _how_to_pay(cfg: dict) -> list[dict]:
    note = (cfg.get("pay_note") or "").strip()
    return [{"name": "How to pay", "value": note[:1000]}] if note else []


def due_ts(sent_at: float, cfg: dict) -> float | None:
    d = int(cfg.get("due_days") or 0)
    return sent_at + d * DAY if d > 0 else None


def fee_message(m: dict, cfg: dict) -> dict:
    """The drop summary, or (m["kind"] == "update") the corrected one after an order changed.
    m: user_id, lines, total, first_ts, last_ts, sent_at; for updates also prev_total, prev_lines, cancelled."""
    update = m.get("kind") == "update"
    lines = m.get("lines") or []
    units = sum(ln["units"] for ln in lines)
    head = f"**{day(m['first_ts'])} drop** · {span(m['first_ts'], m['last_ts'])}"
    count = f"{units} item{'s' * (units != 1)} · {len(lines)} product{'s' * (len(lines) != 1)}"
    body = [head, count]
    if update:
        n = m.get("cancelled") or 0
        why = f"{n} order{'s were' if n != 1 else ' was'} cancelled, so {'they are' if n != 1 else 'it is'} not charged" \
            if n else "Your orders changed"
        body.append(f"~~{money(m.get('prev_total'))}~~ → **{money(m['total'])}** · {why}")
    prev = {ln["key"]: ln for ln in (m.get("prev_lines") or [])} if update else {}
    rows = []
    for ln in lines:
        was = prev.get(ln["key"])
        changed = f" (was {was['units']})" if was and was["units"] != ln["units"] else ""
        rows.append(f"{ln['name']} · {ln['units']} × {money(ln['fee'])}{changed} — **{money(ln['subtotal'])}**")
    for k, was in prev.items():
        if k not in {ln["key"] for ln in lines}:
            rows.append(f"~~{was['name']} · {was['units']} × {money(was['fee'])}~~ — cancelled")
    if rows:
        body.append("\n".join(rows))
    due = due_ts(m["sent_at"], cfg)
    if due and (m["total"] or 0) > 0:
        body.append(f"Due **{day(due)}**")
    name = f"<@{m['user_id']}>"
    return {
        "content": (f"Hey {name}, your {day(m['first_ts'])} drop summary changed." if update
                    else f"Hey {name}, here's your checkout summary for the {day(m['first_ts'])} drop."),
        "color": AMBER if update else GREEN,
        "title": f"{'Updated: you' if update else 'You'} owe {money(m['total'])}",
        "description": "\n\n".join([body[0] + "\n" + body[1]] + body[2:]),
        "fields": _how_to_pay(cfg) if (m["total"] or 0) > 0 else [],
        "footer": FOOTER,
    }


def reminder_message(info: dict, cfg: dict, now: float | None = None) -> dict:
    """Payment reminder for one customer. info = store.open_bills()."""
    now = now or time.time()
    rows = []
    for b in info["bills"]:
        due = f" · due {day(b['due_ts'])}" + (" (**overdue**)" if b["overdue"] else "") if b["due_ts"] else ""
        rows.append(f"{day(b['first_ts'])} drop · **{money(b['open'])}**{due}")
    late = any(b["overdue"] for b in info["bills"])
    desc = "\n".join(rows)
    if info["paid"] > 0.004:
        desc += f"\n\nPaid so far: {money(info['paid'])}"
    return {
        "content": f"Hey <@{info['user_id']}>, a quick reminder about your open balance.",
        "color": RED if late else AMBER,
        "title": f"Payment reminder · {money(info['open'])} open",
        "description": desc,
        "fields": _how_to_pay(cfg),
        "footer": FOOTER,
    }
