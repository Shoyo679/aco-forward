"""Parser, tagging, drops, fees and the ledger. Made-up webhooks only (no real profiles, emails or orders)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot  # noqa: E402
import parse  # noqa: E402
from store import DROP_GAP, Store  # noqa: E402

KEY = b"k" * 32


def valor(profile="nova.runs 3", qty="2", price="$119.98", title="Checked Out! :tada:", order="111-222"):
    return {"title": title, "footer": {"text": "Valor 3.0"}, "thumbnail": {"url": "https://img.example/p.png"},
            "fields": [{"name": "Site", "value": "Target"}, {"name": "Mode", "value": "Default"},
                       {"name": "Product", "value": "[(1234) Sample Box](https://www.target.com/p/x/-/A-1234)"},
                       {"name": "Price", "value": price}, {"name": "Quantity", "value": qty},
                       {"name": "Profile", "value": f"||{profile}||"}, {"name": "Proxy", "value": "||h:1:u:p||"},
                       {"name": "Order Number", "value": f"||{order}||"}, {"name": "Email", "value": "||a@b.c||"}]}


def shikari(profile="kaito_92 a1"):
    return {"author": {"name": "Shikari"}, "title": "Successful Checkout!",
            "description": "[**Sample Bundle**](https://www.walmart.com/ip/sample/987)",
            "fields": [{"name": "Site", "value": "Walmart US"}, {"name": "Profile", "value": profile},
                       {"name": "Quantity", "value": "1"}, {"name": "Order ID", "value": "||999||"}]}


def sniped(profile="mira.cops 1\nmira@example.com"):
    return {"title": "Successful Checkout!", "footer": {"text": "sniped.gg"},
            "fields": [{"name": "Store", "value": "Target"}, {"name": "Profile", "value": profile},
                       {"name": "Product", "value": "Sample Tin"}, {"name": "SKU", "value": "555"},
                       {"name": "Price", "value": "$9.99"}]}


def rec(i, embed, ts=1_000_000.0, sender="Valor"):
    return {"id": str(i), "ts": ts, "channel_id": "c", "guild_id": "g", "source_name": sender,
            "jump_url": "https://discord.com/x", "embeds": [embed]}


class ParseTest(unittest.TestCase):
    def test_tag_rules(self):
        self.assertEqual(parse.tag_of("zeyrox0p 1"), ("zeyrox0p", None))
        self.assertEqual(parse.tag_of("zeyrox0p 1cxd"), ("zeyrox0p", None))
        self.assertEqual(parse.tag_of("Zeyrox0p 2"), ("zeyrox0p", None))
        self.assertEqual(parse.tag_of("zeyrox0p"), ("zeyrox0p", None))
        self.assertEqual(parse.tag_of("zeyrox0p1")[0], "zeyrox0p1")   # no space: whole name (then matches nobody)
        self.assertIsNone(parse.tag_of("Zey-Main 1")[0])               # "-" can't be in a username
        self.assertIsNone(parse.tag_of(None)[0])

    def test_valor(self):
        p = parse.parse(rec(1, valor()), KEY)
        self.assertEqual((p["kind"], p["bot"], p["tag"], p["qty"], p["price"]), ("success", "valor", "nova.runs", 2, 59.99))
        self.assertEqual((p["product_id"], p["product_name"]), ("1234", "Sample Box"))
        self.assertTrue(p["order_fp"] and "111" not in p["order_fp"])
        self.assertEqual(p["order_number"], "111-222")      # for the runner's Checkouts tab only
        flat = repr(p)
        for private in ("a@b.c", "h:1:u:p"):
            self.assertNotIn(private, flat)

    def test_shikari_and_sniped(self):
        s = parse.parse(rec(2, shikari(), sender="Shikari"), KEY)
        self.assertEqual((s["bot"], s["tag"], s["product_name"], s["store"]), ("shikari", "kaito_92", "Sample Bundle", "Walmart"))
        n = parse.parse(rec(3, sniped(), sender="sniped.gg"), KEY)
        self.assertEqual((n["bot"], n["tag"], n["profile"]), ("sniped", "mira.cops", "mira.cops 1"))
        self.assertNotIn("example.com", repr(n))

    def test_others(self):
        self.assertEqual(parse.parse(rec(4, valor(title="Card Declined!")), KEY)["kind"], "other")
        self.assertEqual(parse.parse(rec(5, {"title": "Webhook Test", "footer": {"text": "Valor"}}), KEY)["kind"], "test")
        self.assertEqual(parse.parse(rec(6, {"title": "Checked out", "fields": [{"name": "a", "value": "b"}]},
                                         sender="Stellar"), KEY)["kind"], "unknown_sender")
        self.assertEqual(parse.parse(rec(7, valor(title="Order Canceled! (Policy - Item Demand)")), KEY)["kind"], "cancel")
        self.assertEqual(parse.parse(rec(8, {**shikari(), "title": "Order Canceled: Item Demand"}), KEY)["kind"], "cancel")
        self.assertEqual(parse.parse(rec(9, valor(title="Order Still Good")), KEY)["kind"], "other")
        self.assertEqual(parse.parse(rec(10, {**shikari(), "title": "Successful Checkout (Review Hold)"}), KEY)["kind"],
                         "success")

    def test_post_has_only_product_site_qty_profile(self):
        c = {"cancelled": 0, "user_id": "42", "problem": None, "profile": "nova.runs 3", "product_name": "Sample Box",
             "qty": 2, "image": None, "price": 59.99, "store": "Target", "bot": "valor", "order_number": "777-1"}
        content, e = bot.post_parts(c)
        self.assertIn("<@42>", content)
        self.assertEqual(e.description, "**Product:** Sample Box\n**Site:** Target\n**Qty:** 2\n"
                                        "**Profile:** ||nova.runs 3||")          # one line each, profile hidden
        self.assertEqual(e.fields, [])
        flat = repr(e.to_dict()) + content
        for left_out in ("59", "valor", "777-1"):
            self.assertNotIn(left_out, flat.lower())
        self.assertIsNone(e.to_dict().get("footer"))

    def test_post_spoiler_edge_cases(self):
        base = {"cancelled": 0, "user_id": None, "problem": None, "product_name": "Box", "qty": 1, "image": None}
        content, e = bot.post_parts({**base, "profile": "bad|name 1", "store": None})
        self.assertIn("**Profile:** ||badname 1||", e.description)                 # "|" can't break the spoiler
        self.assertIn("**Site:** —", e.description)
        self.assertIn("profile ||`badname 1`||", content)                           # unassigned line hidden too
        _, e2 = bot.post_parts({**base, "profile": None, "store": "Walmart", "user_id": "1"})
        self.assertIn("**Profile:** —", e2.description)                             # added by hand: no profile


class _StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name) / "t.db")
        self.members = {"nova.runs": ("1", "nova.runs"), "kaito_92": ("2", "kaito_92")}
        self.match = lambda t: self.members.get(t)

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def add(self, i, embed, ts, sender="Valor"):
        r = rec(i, embed, ts, sender)
        return self.s.add_checkout(r, parse.parse(r, KEY), self.match)


class StoreTest(_StoreBase):
    def test_match_assign_remember(self):
        a = self.add(1, valor(), 1000)
        b = self.add(2, valor(profile="novaruns3"), 1010)
        self.assertEqual((a["user_id"], a["how"]), ("1", "auto"))
        self.assertIsNone(b["user_id"])
        self.assertIsNone(self.add(1, valor(), 1000))              # same message again (catch-up): ignored
        self.s.assign(["2"], "1", "nova.runs", remember=True)
        c = self.add(3, valor(profile="novaruns3"), 1020)
        self.assertEqual((c["user_id"], c["how"]), ("1", "rule"))   # remembered profile name
        self.assertEqual(len(self.s.unmatched()), 0)

    def test_rematch_when_member_joins(self):
        self.add(1, valor(profile="late.joiner 1"), 1000)
        self.assertEqual(self.s.rematch(self.match), [])
        self.members["late.joiner"] = ("9", "late.joiner")
        self.assertEqual(self.s.rematch(self.match)[0]["user_id"], "9")

    def test_drops_split_and_combine(self):
        self.add(1, valor(), 0)
        self.add(2, valor(), 60 * 60)                          # 60 min later: same drop
        self.add(3, valor(), 60 * 60 + DROP_GAP + 1)           # > 90 min quiet: new drop
        ds = self.s.drops()
        self.assertEqual([d["checkouts"] for d in ds], [1, 2])
        grp = self.s.combine([d["key"] for d in ds])
        ds = self.s.drops()
        self.assertEqual(len(ds), 1)
        self.assertEqual((ds[0]["key"], ds[0]["checkouts"], ds[0]["combined"]), (grp, 3, True))
        self.s.uncombine(grp)
        self.assertEqual(len(self.s.drops()), 2)

    def test_summary_bill_and_ledger(self):
        self.add(1, valor(qty="2"), 0)                                        # nova: 2 units of 1234
        self.add(2, shikari(), 100, sender="Shikari")                         # kaito: 1 unit of 987
        self.add(3, valor(profile="nobody 1", qty="1"), 200)                  # unassigned
        self.add(4, valor(qty="1", order="333"), 300)                         # nova, later cancelled
        self.s.cancel_by_order(parse.order_fp("333", KEY))
        key = self.s.drops()[0]["key"]
        s = self.s.summary(key, {})
        self.assertEqual(len(s["blockers"]), 2)                              # fees + 1 unassigned
        with self.assertRaises(ValueError):
            self.s.bill(key, {"1234": 15, "987": 8})
        self.s.assign(["3"], "2", "kaito_92", remember=False)
        done = self.s.bill(key, {"1234": 15, "987": 8})
        totals = {c["user_name"]: c["total"] for c in done["customers"]}
        self.assertEqual(totals, {"nova.runs": 30, "kaito_92": 23})          # cancelled one not charged
        self.assertTrue(done["sent"])
        self.assertEqual(len(self.s.pending_messages(key)), 2)
        with self.assertRaises(ValueError):
            self.s.bill(key, {"1234": 15, "987": 8})                        # never twice
        self.assertEqual(self.s.assign(["1"], "2", "kaito_92", False), [])   # billed rows can't move
        self.add(5, valor(), 400)                                           # after the bill: a new drop
        self.assertEqual(len(self.s.drops()), 2)
        with self.assertRaises(ValueError):
            self.s.combine([d["key"] for d in self.s.drops()])              # sent drop can't be combined
        self.assertEqual(self.s.pay("1", None, None), 30)
        bal = {b["user_name"]: b["owed"] for b in self.s.balances()}
        self.assertEqual(bal, {"nova.runs": 0, "kaito_92": 23})
        self.assertEqual(self.s.last_fees(), {"1234": 15, "987": 8})


class StatusAndMessagesTest(_StoreBase):
    """Order status, bills that change after sending, reminders, combine neighbours, the DM text."""

    def billed_drop(self):
        self.add(1, valor(qty="2", order="o1"), 0)           # nova: 2 x 1234
        self.add(2, valor(qty="1", order="o2"), 60)          # nova: 1 x 1234
        self.add(3, shikari(), 120, sender="Shikari")        # kaito: 1 x 987
        key = self.s.drops()[0]["key"]
        self.s.bill(key, {"1234": 15, "987": 8})
        for m in self.s.pending_messages(key):
            self.s.message_result(m["bill"], m["user_id"], True)
        return key

    def owed(self):
        return {b["user_name"]: b["owed"] for b in self.s.balances()}

    def test_status_before_bill_changes_fees(self):
        self.add(1, valor(qty="2"), 0)
        self.add(2, valor(qty="1", order="o2"), 60)
        key = self.s.drops()[0]["key"]
        self.s.set_status("2", True)
        self.assertEqual(self.s.summary(key, {"1234": 15})["customers"][0]["total"], 30)
        self.assertEqual(self.s.checkout("2")["cancel_by"], "you")
        self.s.set_status("2", False)
        self.assertEqual(self.s.summary(key, {"1234": 15})["customers"][0]["total"], 45)

    def test_status_after_bill_rebills_and_update(self):
        key = self.billed_drop()
        self.assertEqual(self.owed(), {"nova.runs": 45, "kaito_92": 8})
        self.s.set_status("2", True)                                      # nova's 1-item order cancelled
        self.assertEqual(self.owed()["nova.runs"], 30)
        c = next(c for c in self.s.summary(key, {})["customers"] if c["user_name"] == "nova.runs")
        self.assertEqual((c["total"], c["sent_total"], c["changed"]), (30, 45, True))
        self.assertEqual(len(self.s.changed_unsent()), 1)
        self.s.queue_update(key, "1")
        m = self.s.pending_messages(key)[0]
        self.assertEqual((m["kind"], m["prev_total"], m["total"]), ("update", 45, 30))
        self.s.message_result(key, "1", True)
        self.assertEqual(self.s.changed_unsent(), [])
        with self.assertRaises(ValueError):
            self.s.queue_update(key, "1")                                 # nothing changed since
        self.s.set_status("2", False)                                     # back to active: charged again
        self.assertEqual(self.owed()["nova.runs"], 45)
        self.s.pay("2", 8, None)
        self.s.set_status("3", True)                                      # kaito paid, then cancelled: credit
        self.assertEqual(self.owed()["kaito_92"], -8)
        kaito = next(c for c in self.s.summary(key, {})["customers"] if c["user_name"] == "kaito_92")
        self.assertEqual((kaito["total"], kaito["lines"]), (0, []))       # still listed, so they can be told

    def test_bot_cancel_after_bill(self):
        self.billed_drop()
        self.s.cancel_by_order(parse.order_fp("o1", KEY), "Valor")
        self.assertEqual(self.owed()["nova.runs"], 15)
        self.assertEqual(self.s.checkout("1")["cancel_by"], "Valor")

    def test_open_bills_oldest_first(self):
        k1 = self.billed_drop()                                          # nova owes 45
        self.add(4, valor(qty="1"), 10 * DROP_GAP)                       # a later drop: nova 1 x 1234
        k2 = self.s.drops()[0]["key"]
        self.s.bill(k2, {"1234": 20})
        self.s.pay("1", 50, None)                                        # pays drop 1 (45) + 5 of drop 2
        sent = self.s.q("SELECT sent_at FROM bills WHERE key=?", (k2,))[0]["sent_at"]
        info = self.s.open_bills("1", due_days=2, now=sent + 3 * 86400)
        self.assertEqual(info["open"], 15)
        self.assertEqual([(b["key"], b["open"], b["overdue"]) for b in info["bills"]], [(k2, 15, True)])
        self.assertFalse(self.s.open_bills("1", due_days=2, now=sent + 86400)["bills"][0]["overdue"])
        self.assertEqual(self.s.open_bills("1", due_days=0)["bills"][0]["due_ts"], None)
        self.assertNotEqual(k1, k2)

    def test_combine_neighbours_skip_sent(self):
        self.add(1, valor(), 0)                          # A open
        self.add(2, valor(), DROP_GAP * 2)               # B (sent below)
        self.add(3, valor(), DROP_GAP * 4)               # C open
        self.add(4, valor(), DROP_GAP * 6)               # D open
        b = [d for d in self.s.drops() if d["first"] == DROP_GAP * 2][0]["key"]
        self.s.bill(b, {"1234": 1})
        keys = {d["first"]: d["key"] for d in self.s.drops()}
        a, c, d = keys[0], keys[DROP_GAP * 4], keys[DROP_GAP * 6]
        with self.assertRaises(ValueError):
            self.s.combine([a, d])                       # C is between them
        g = self.s.combine([a, c])                       # sent B between them is skipped
        combined = next(x for x in self.s.drops() if x["key"] == g)
        self.assertEqual((combined["checkouts"], len(combined["spans"])), (2, 2))
        self.s.combine([g, d])                           # a combined drop + its next neighbour
        self.assertEqual(len([x for x in self.s.drops() if not x["sent"]]), 1)

    def test_messages(self):
        import messages
        key = self.billed_drop()
        cfg = {"pay_note": "Cash App $x", "due_days": 2}
        m = self.s.message_data(self.s.message(key, "1"))
        msg = messages.fee_message(m, cfg)
        self.assertEqual(msg["title"], "You owe $45")
        self.assertIn("Sample Box · 3 × $15 — **$45**", msg["description"])
        self.assertIn("Due **", msg["description"])
        self.assertEqual(msg["fields"], [{"name": "How to pay", "value": "Cash App $x"}])
        self.s.set_status("2", True)
        self.s.queue_update(key, "1")
        up = messages.fee_message(self.s.message_data(self.s.pending_messages(key)[0]), cfg)
        self.assertEqual(up["title"], "Updated: you owe $30")
        self.assertIn("~~$45~~ → **$30** · 1 order was cancelled", up["description"])
        self.assertIn("2 × $15 (was 3)", up["description"])
        rem = messages.reminder_message(self.s.open_bills("1", 2), cfg)
        self.assertEqual(rem["title"], "Payment reminder · $30 open")
        flat = repr(msg) + repr(up) + repr(rem)
        for private in ("o1", "o2", "a@b.c", "h:1:u:p"):
            self.assertNotIn(private, flat)


class ScaleAndBackupTest(_StoreBase):
    """Adding missed checkouts by hand, the Checkouts tab pages, grouped tagged posts, order numbers."""

    def test_add_manual(self):
        self.add(1, valor(order="111-222"), 0)
        c = self.s.add_manual("2", "kaito_92", "Sample Box", 2, "999-1", 30, KEY, post=True)
        self.assertEqual((c["user_id"], c["how"], c["source"], c["qty"], c["post_wait"]), ("2", "manual", "manual", 2, 1))
        self.assertEqual(c["product_key"], "1234")                          # same product as the webhook one
        self.assertEqual(self.s.drops()[0]["checkouts"], 2)                  # lands in the same drop
        with self.assertRaises(ValueError):
            self.s.add_manual("2", "kaito_92", "Sample Box", 1, "111-222", 40, KEY)   # already saved (webhook)
        with self.assertRaises(ValueError):
            self.s.add_manual("2", "kaito_92", "Sample Box", 1, "999-1", 40, KEY)     # already added
        with self.assertRaises(ValueError):
            self.s.add_manual("2", "kaito_92", " ", 1, None, 40, KEY)

    def test_checkouts_page(self):
        for i in range(250):
            self.add(i + 1, valor(order=f"o{i}", profile="nova.runs 1" if i % 5 else "kaito_92 1"), i * 10)
        self.s.set_status("3", True)
        key = self.s.drops()[0]["key"]
        p = self.s.checkouts_page(drop=key, offset=200, limit=100)
        self.assertEqual((p["total"], len(p["rows"])), (250, 50))
        self.assertEqual({x["user_name"]: x["n"] for x in p["people"]}, {"nova.runs": 199, "kaito_92": 50})
        self.assertEqual(self.s.checkouts_page(drop=key, user="2")["total"], 50)
        self.assertEqual(self.s.checkouts_page(status="cancelled")["total"], 1)
        hit = self.s.checkouts_page(text="o249")["rows"]
        self.assertEqual([r["order_number"] for r in hit], ["o249"])

    def test_grouped_post(self):
        rows = [{"cancelled": 0, "user_id": u, "user_name": n, "problem": None, "profile": f"{n} 1",
                 "product_name": "Sample Box", "qty": 1, "image": None, "order_number": "555-1"}
                for u, n in (("1", "nova.runs"), ("2", "kaito_92"), ("1", "nova.runs"))]
        rows.append({**rows[0], "user_id": None, "user_name": None, "problem": "Doesn't start with a Discord username"})
        content, embeds = bot.post_batch_parts(rows)
        self.assertEqual(content.splitlines()[0], "<@1> <@2> checked out")   # each person tagged once
        self.assertIn("1 unassigned", content)
        self.assertEqual(len(embeds), 4)
        self.assertNotIn("555-1", content + repr([e.to_dict() for e in embeds]))   # order numbers never posted
        self.assertEqual(len(bot.post_batch_parts(rows * 5)[1]), 10)            # Discord's limit per message

    def test_post_queue(self):
        self.s.add_checkout(rec(1, valor(), 0), parse.parse(rec(1, valor(), 0), KEY), self.match, post=True)
        self.s.add_checkout(rec(2, valor(), 5), parse.parse(rec(2, valor(), 5), KEY), self.match, post=True)
        self.assertEqual(self.s.post_backlog(), 2)
        self.s.set_posted(["1", "2"], "m1", "ch")
        self.assertEqual((self.s.post_backlog(), len(self.s.posted_group("m1"))), (0, 2))

    def test_sent_drop_counts_match(self):
        self.add(1, valor(qty="2"), 0)
        self.add(2, shikari(), 10, sender="Shikari")
        self.add(3, valor(profile="nobody 1"), 20)
        before = {k: v for k, v in self.s.drops()[0].items() if k in ("checkouts", "units", "customers", "first", "last")}
        key = self.s.drops()[0]["key"]
        self.s.assign(["3"], "2", "kaito_92", False)
        self.s.bill(key, {"1234": 1, "987": 1})
        after = self.s.drops()[0]
        self.assertTrue(after["sent"])
        self.assertEqual({k: after[k] for k in before}, {**before, "customers": 2})


if __name__ == "__main__":
    unittest.main()
