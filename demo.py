"""--demo: made-up customers and checkouts in demo-data/ so the dashboard can be tried without Discord.
Nothing here talks to Discord; "sent" DMs are pretend (one customer's DM fails on purpose, to show that case)."""
from __future__ import annotations

import random
import threading
import time

import parse

MEMBERS = {"nova.runs": "101", "kaito_92": "102", "mira.cops": "103", "jules.fx": "104", "rio.restocks": "105",
           "dex_tcg": "106", "ash.flips": "107"}
PRODUCTS = [("90001", "Prismatic Evolutions Elite Trainer Box", "Target", 59.99),
            ("90002", "Surging Sparks Booster Bundle", "Walmart", 26.94),
            ("90003", "151 Ultra Premium Collection", "Target", 119.99),
            ("90004", "Journey Together Booster Box", "Walmart", 161.64),
            ("90005", "Destined Rivals Sleeved Booster", "Target", 4.99)]
SERVERS = [{"id": "s1", "name": "Shoyo's ACO", "icon": None, "members": 9, "channels": [
    {"id": "1001", "name": "valor-success", "category": "BOTS", "read": True, "post": False},
    {"id": "1002", "name": "shikari-success", "category": "BOTS", "read": True, "post": False},
    {"id": "1003", "name": "sniped-success", "category": "BOTS", "read": True, "post": False},
    {"id": "1004", "name": "refract-success", "category": "BOTS", "read": False, "post": False},
    {"id": "1005", "name": "general", "category": "", "read": True, "post": True}]},
    {"id": "s2", "name": "ACO Customers", "icon": None, "members": 41, "channels": [
        {"id": "2001", "name": "announcements", "category": "INFO", "read": True, "post": False},
        {"id": "2002", "name": "checkouts", "category": "ACO", "read": True, "post": True},
        {"id": "2003", "name": "support", "category": "ACO", "read": True, "post": True}]}]


class FakeForwarder:
    def __init__(self, store, get_cfg, broadcast) -> None:
        self.store, self.get_cfg, self.broadcast = store, get_cfg, broadcast
        self.state, self.error = "online", None
        self.me = {"name": "Shoyo ACO", "id": "999", "avatar": None}
        self.members = {u: (i, u) for u, i in MEMBERS.items()}

    def start(self, token) -> None:
        self.state = "online"
        self.broadcast("state")

    def stop(self) -> None:
        pass

    def match(self, tag):
        return self.members.get(tag) if tag else None

    def member_search(self, text, limit=12):
        t = (text or "").lower().lstrip("@")
        return [{"user_id": i, "user_name": u} for u, (i, _) in sorted(self.members.items()) if t in u][:limit]

    def servers(self):
        return SERVERS

    def channel_health(self):
        cfg = self.get_cfg()
        names = {c["id"]: f"{s['name']} › #{c['name']}" for s in SERVERS for c in s["channels"]}
        out = [{"id": c, "role": "source", "name": names.get(c, c), "ok": True, "problem": None} for c in cfg["sources"]]
        if cfg.get("output"):
            out.append({"id": cfg["output"], "role": "output", "name": names.get(cfg["output"]), "ok": True,
                        "problem": None})
        return out

    def repost(self, rows) -> None:
        pass

    def kick(self) -> None:
        """Pretend the queued tagged posts went out."""
        rows = self.store.waiting_posts(1000)
        if rows:
            self.store.set_posted([c["id"] for c in rows], "demo", self.get_cfg().get("output") or "")

    def send_pending(self, key) -> None:
        def go() -> None:
            for m in self.store.pending_messages(key):
                time.sleep(0.6)
                ok = m["user_name"] != "dex_tcg"
                self.store.message_result(m["bill"], m["user_id"], ok,
                                          None if ok else "Their DMs are closed to this bot (or they share no server with it).")
                self.broadcast("data")
        threading.Thread(target=go, daemon=True).start()

    def send_reminder(self, user_id, msg) -> None:
        if self.members.get("dex_tcg", ("",))[0] == user_id:
            raise RuntimeError("Their DMs are closed to this bot (or they share no server with it).")

    def test_post(self) -> str:
        return "Posted in #checkouts (demo)"


def seed(store, cfg, bot) -> None:
    if store.q("SELECT 1 FROM checkouts LIMIT 1"):
        return
    cfg.update(sources=["1001", "1002", "1003"], output="2002",
               names={"1001": "Shoyo's ACO › #valor-success", "1002": "Shoyo's ACO › #shikari-success",
                      "1003": "Shoyo's ACO › #sniped-success", "2002": "ACO Customers › #checkouts"},
               token="demo")
    rnd = random.Random(7)
    now = time.time()
    n = 0
    # three drops: 3 days ago (sent + partly paid), yesterday (two bursts 2 h apart), this morning (live)
    for start, count, spread in ((now - 3 * 86400, 14, 70), (now - 86400 - 2 * 3600, 9, 40),
                                 (now - 86400 + 15 * 60, 6, 30), (now - 2.2 * 3600, 17, 120)):
        for i in range(count):
            n += 1
            user = rnd.choice(list(MEMBERS) + ["nova.runs", "kaito_92"])
            pid, name, store_name, price = rnd.choice(PRODUCTS[:4] if i % 3 else PRODUCTS)
            prof = f"{user} {rnd.choice(['1', '2', '3', 'a7', '1cxd', 'main'])}"
            if n in (31, 37, 40):
                prof = rnd.choice(["novaruns 4", "Kaito-92 2", "mira 1"])   # wrong profile names
            ts = start + i * spread * 60 / max(1, count) + rnd.random() * 30
            p = {"kind": "success", "bot": rnd.choice(["valor", "shikari", "sniped", "refract"]), "store": store_name,
                 "product_id": pid, "product_name": name, "product_key": pid, "price": price,
                 "qty": rnd.choice([1, 1, 1, 2]), "profile": prof, "order_fp": f"fp{n}", "image": None}
            p["tag"], p["problem"] = parse.tag_of(prof)
            store.add_checkout({"id": f"{100000 + n}", "ts": ts, "channel_id": "1001", "guild_id": "s1",
                                "jump_url": ""}, p, bot.match)
    store.cancel_by_order("fp5", "Valor")
    first = store.drops()[-1]["key"]
    fees = {"90001": 15, "90002": 8, "90003": 25, "90004": 30, "90005": 3}
    store.bill(first, fees)
    for m in store.pending_messages(first):
        store.message_result(m["bill"], m["user_id"], True)
    for b in store.balances()[:2]:
        store.pay(b["user_id"], None, "PayPal")
    store.x("UPDATE ledger SET ts=ts-3*86400")
    store.x("UPDATE bills SET sent_at=sent_at-3*86400")   # so its due date has passed: shows Overdue
    cfg["pay_note"] = "Pay within 2 days to Cash App $demo-runner or PayPal demo@example.com"
    store.skip("Stellar", now - 5000)
