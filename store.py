"""Everything ACO Forward keeps, in one SQLite file (data/forward.db), and the rules that work on it:
customer matching, drops (90 quiet minutes, combine / undo), fee summaries and the owed / paid ledger.

All writes go through one lock, so the bot thread and the dashboard never step on each other.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import contextmanager

DROP_GAP = 90 * 60   # a drop ends after 90 minutes with no checkouts (same rule as Archon)

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkouts(
  id TEXT PRIMARY KEY, ts REAL, channel_id TEXT, guild_id TEXT, bot TEXT, store TEXT,
  product_id TEXT, product_name TEXT, product_key TEXT, price REAL, qty INTEGER,
  profile TEXT, tag TEXT, problem TEXT,
  user_id TEXT, user_name TEXT, how TEXT,           -- how: auto / rule / manual
  cancelled INTEGER DEFAULT 0, order_fp TEXT, image TEXT, jump_url TEXT,
  posted_id TEXT, posted_channel TEXT, billed TEXT);
CREATE INDEX IF NOT EXISTS ck_ts ON checkouts(ts);
CREATE INDEX IF NOT EXISTS ck_fp ON checkouts(order_fp);
CREATE TABLE IF NOT EXISTS rules(profile TEXT PRIMARY KEY, user_id TEXT, user_name TEXT);
CREATE TABLE IF NOT EXISTS combos(member TEXT PRIMARY KEY, grp TEXT);
CREATE TABLE IF NOT EXISTS fees(product_key TEXT PRIMARY KEY, fee REAL);
CREATE TABLE IF NOT EXISTS bills(key TEXT PRIMARY KEY, sent_at REAL, first_ts REAL, last_ts REAL, fees TEXT);
CREATE TABLE IF NOT EXISTS messages(bill TEXT, user_id TEXT, user_name TEXT, total REAL, lines TEXT,
  status TEXT, error TEXT, sent_at REAL, PRIMARY KEY(bill, user_id));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, user_name TEXT,
  amount REAL, kind TEXT, bill TEXT, ts REAL, note TEXT);
CREATE TABLE IF NOT EXISTS skipped(sender TEXT PRIMARY KEY, n INTEGER, last_ts REAL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS reminders(user_id TEXT PRIMARY KEY, ts REAL, amount REAL);
"""
# columns added after the first version (older data files get them on start-up)
MIGRATIONS = [("checkouts", "cancel_by", "TEXT"), ("messages", "kind", "TEXT DEFAULT 'summary'"),
              ("messages", "prev_total", "REAL"), ("messages", "prev_lines", "TEXT"),
              ("checkouts", "order_number", "TEXT"),     # shown to the runner only, never posted or DMed
              ("checkouts", "source", "TEXT DEFAULT 'webhook'"),   # webhook / manual (added by the runner)
              ("checkouts", "post_wait", "INTEGER DEFAULT 0")]     # 1 = tagged post still to be sent
INDEXES = """
CREATE INDEX IF NOT EXISTS ck_billed ON checkouts(billed);
CREATE INDEX IF NOT EXISTS ck_user ON checkouts(user_id);
CREATE INDEX IF NOT EXISTS ck_order ON checkouts(order_number);
CREATE INDEX IF NOT EXISTS ck_wait ON checkouts(post_wait);
CREATE INDEX IF NOT EXISTS ck_posted ON checkouts(posted_id);
"""
DAY = 86400


class Store:
    def __init__(self, path) -> None:
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.version = 0          # goes up on every write; cached results are reused until it changes
        self._depth = 0
        self._cache: dict = {}
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")      # fast, safe writes (a checkout every few ms in a drop)
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.executescript(SCHEMA)
            for table, col, kind in MIGRATIONS:
                cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
            self.db.executescript(INDEXES)
            self.db.commit()

    # ---------------- small helpers ----------------
    def q(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            self.version += 1
            if not self._depth:
                self.db.commit()
            return cur.rowcount

    @contextmanager
    def batch(self):
        """Many writes saved together in one go (all or nothing)."""
        with self.lock:
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if not self._depth:
                    self.db.rollback()
                    self.version += 1
                raise
            self._depth -= 1
            if not self._depth:
                self.db.commit()

    def _cached(self, name: str, fn):
        hit = self._cache.get(name)
        if hit and hit[0] == self.version:
            return hit[1]
        val = fn()
        self._cache[name] = (self.version, val)
        return val

    def meta(self, k: str, default=None):
        r = self.q("SELECT v FROM meta WHERE k=?", (k,))
        return json.loads(r[0]["v"]) if r else default

    def set_meta(self, k: str, v) -> None:
        self.x("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v)))

    # ---------------- checkouts ----------------
    def add_checkout(self, rec: dict, parsed: dict, match, post: bool = False) -> dict | None:
        """Save a new checkout and tag it. match(tag) -> (user_id, user_name) or None. post = queue its tagged post.
        Returns the saved row, or None if it was already saved (catch-up after a restart)."""
        with self.lock:
            if self.q("SELECT 1 FROM checkouts WHERE id=?", (rec["id"],)):
                return None
            uid = uname = how = None
            rule = self.q("SELECT * FROM rules WHERE profile=?", ((parsed["profile"] or "").lower(),))
            if rule:
                uid, uname, how = rule[0]["user_id"], rule[0]["user_name"], "rule"
            elif parsed["tag"]:
                hit = match(parsed["tag"])
                if hit:
                    uid, uname, how = hit[0], hit[1], "auto"
            self.x("""INSERT INTO checkouts(id,ts,channel_id,guild_id,bot,store,product_id,product_name,product_key,
                      price,qty,profile,tag,problem,user_id,user_name,how,order_fp,image,jump_url,order_number,source,
                      post_wait) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (rec["id"], rec["ts"], rec.get("channel_id"), rec.get("guild_id"), parsed["bot"], parsed["store"],
                    parsed["product_id"], parsed["product_name"], parsed["product_key"], parsed["price"],
                    parsed["qty"], parsed["profile"], parsed["tag"], parsed["problem"], uid, uname, how,
                    parsed["order_fp"], parsed["image"], rec.get("jump_url"), parsed.get("order_number"),
                    parsed.get("source", "webhook"), int(post)))
            return self.checkout(rec["id"])

    def add_manual(self, user_id: str, user_name: str, product_name: str, qty: int, order_number: str | None,
                   ts: float, key: bytes, post: bool = False) -> dict:
        """A checkout the checkout bot never posted (Discord dropped or rate-limited its webhook), added by the
        runner. Refused if a checkout with the same order number is already saved, so nobody is billed twice."""
        import parse
        product_name = (product_name or "").strip()[:200]
        order_number = (order_number or "").strip()[:80] or None
        if not product_name:
            raise ValueError("Enter the product.")
        if not 1 <= int(qty) <= 99:
            raise ValueError("Quantity must be between 1 and 99.")
        fp = parse.order_fp(order_number, key)
        if order_number and self.q("SELECT 1 FROM checkouts WHERE order_number=? OR order_fp=?", (order_number, fp)):
            raise ValueError(f"Order {order_number} is already saved.")
        known = self.q("SELECT product_key, product_id, store, image FROM checkouts WHERE lower(product_name)=? "
                       "ORDER BY ts DESC LIMIT 1", (product_name.lower(),))
        k = known[0] if known else {}
        p = {"kind": "success", "bot": "manual", "store": k.get("store"), "product_id": k.get("product_id"),
             "product_name": product_name, "product_key": k.get("product_key") or product_name.lower(),
             "price": None, "qty": int(qty), "profile": None, "tag": None, "problem": None, "order_fp": fp,
             "image": k.get("image"), "order_number": order_number, "source": "manual"}
        cid = "m" + secrets.token_hex(8)
        with self.batch():
            self.add_checkout({"id": cid, "ts": float(ts)}, p, lambda t: None, post=post)
            self.x("UPDATE checkouts SET user_id=?, user_name=?, how='manual' WHERE id=?", (user_id, user_name, cid))
        return self.checkout(cid)

    def checkout(self, cid: str) -> dict | None:
        r = self.q("SELECT * FROM checkouts WHERE id=?", (cid,))
        return r[0] if r else None

    def cancel_by_order(self, fp: str | None, by: str = "bot") -> dict | None:
        """A checkout bot said an order was cancelled (same order number): the checkout no longer counts for fees."""
        if not fp:
            return None
        r = self.q("SELECT * FROM checkouts WHERE order_fp=? AND cancelled=0 ORDER BY ts DESC LIMIT 1", (fp,))
        return self.set_status(r[0]["id"], True, by) if r else None

    def set_status(self, cid: str, cancelled: bool, by: str = "you") -> dict | None:
        """Active <-> Cancelled. A cancelled checkout isn't charged. If its drop was already billed, that customer's
        bill for the drop is worked out again with the fees used then, and their balance moves by the difference."""
        with self.lock:
            c = self.checkout(cid)
            if not c or bool(c["cancelled"]) == cancelled:
                return c
            self.x("UPDATE checkouts SET cancelled=?, cancel_by=? WHERE id=?",
                   (int(cancelled), by if cancelled else None, cid))
            if c["billed"] and c["user_id"]:
                self._rebill(c["billed"], c["user_id"], c["user_name"],
                             "Order cancelled" if cancelled else "Order active again")
            return self.checkout(cid)

    def set_posted(self, ids: list[str], msg_id: str, channel_id: str) -> None:
        with self.batch():
            for cid in ids:
                self.x("UPDATE checkouts SET posted_id=?, posted_channel=?, post_wait=0 WHERE id=?",
                       (msg_id, channel_id, cid))

    def waiting_posts(self, limit: int = 10) -> list[dict]:
        """Tagged posts still to send, oldest first (kept across restarts)."""
        return self.q("SELECT * FROM checkouts WHERE post_wait=1 ORDER BY ts LIMIT ?", (limit,))

    def post_backlog(self) -> int:
        return self.q("SELECT COUNT(*) AS n FROM checkouts WHERE post_wait=1")[0]["n"]

    def drop_post(self, cid: str) -> None:
        self.x("UPDATE checkouts SET post_wait=0 WHERE id=?", (cid,))

    def posted_group(self, msg_id: str) -> list[dict]:
        """All checkouts shown in one tagged message (a grouped post holds up to 10)."""
        return self.q("SELECT * FROM checkouts WHERE posted_id=? ORDER BY ts", (msg_id,))

    def checkouts_page(self, drop: str | None = None, user: str | None = None, status: str | None = None,
                       text: str | None = None, offset: int = 0, limit: int = 100) -> dict:
        """One page of the Checkouts tab, filtered on this side so a 2,000-checkout drop is never cut off."""
        where, args = [], []
        if drop:
            if self.q("SELECT 1 FROM bills WHERE key=?", (drop,)):
                where.append("billed=?")
                args.append(drop)
            else:
                ids = [i for i, k in self.open_drop_map().items() if k == drop]
                if not ids:
                    return {"rows": [], "total": 0, "people": []}
                where.append("id IN (SELECT value FROM json_each(?))")
                args.append(json.dumps(ids))
        if user == "_":
            where.append("user_id IS NULL")
        elif user:
            where.append("user_id=?")
            args.append(user)
        if status in ("active", "cancelled"):
            where.append("cancelled=?")
            args.append(int(status == "cancelled"))
        if text:
            where.append("(lower(product_name) LIKE ? OR lower(profile) LIKE ? OR lower(user_name) LIKE ? "
                         "OR lower(order_number) LIKE ? OR lower(store) LIKE ?)")
            args += [f"%{text.lower()}%"] * 5
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.q(f"SELECT COUNT(*) AS n FROM checkouts{w}", args)[0]["n"]
        rows = self.q(f"SELECT * FROM checkouts{w} ORDER BY ts DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        open_map = self.open_drop_map()
        for r in rows:
            r["drop"] = r["billed"] or open_map.get(r["id"])
        # per-customer chips (same filters except the customer one)
        w2 = [c for c in where if not c.startswith("user_id")]
        a2 = list(args)
        if user and user != "_":
            a2.remove(user)
        w2s = (" WHERE " + " AND ".join(w2)) if w2 else ""
        people = self.q(f"""SELECT user_id, MAX(user_name) AS user_name, SUM(cancelled=0) AS n,
                            SUM(CASE WHEN cancelled=0 THEN qty ELSE 0 END) AS units
                            FROM checkouts{w2s} GROUP BY user_id ORDER BY n DESC LIMIT 1000""", a2)
        return {"rows": rows, "total": total, "people": people}

    def unmatched(self) -> list[dict]:
        return self.q("SELECT * FROM checkouts WHERE user_id IS NULL AND billed IS NULL AND cancelled=0 "
                      "ORDER BY ts DESC")

    def rematch(self, match) -> list[dict]:
        """Try again for untagged checkouts (members load after start-up, someone joined, a rule was added)."""
        changed = []
        for c in self.unmatched():
            rule = self.q("SELECT * FROM rules WHERE profile=?", ((c["profile"] or "").lower(),))
            hit = (rule[0]["user_id"], rule[0]["user_name"], "rule") if rule else \
                (*match(c["tag"]), "auto") if c["tag"] and match(c["tag"]) else None
            if hit:
                self.x("UPDATE checkouts SET user_id=?, user_name=?, how=? WHERE id=?", (*hit, c["id"]))
                changed.append(self.checkout(c["id"]))
        return changed

    def assign(self, ids: list[str], user_id: str, user_name: str, remember: bool) -> list[dict]:
        """The runner gives checkouts to a customer by hand. Billed checkouts can't move (already charged)."""
        out = []
        with self.lock:
            for cid in ids:
                c = self.checkout(cid)
                if not c or c["billed"]:
                    continue
                self.x("UPDATE checkouts SET user_id=?, user_name=?, how='manual' WHERE id=?",
                       (user_id, user_name, cid))
                if remember and c["profile"]:
                    self.x("INSERT OR REPLACE INTO rules VALUES(?,?,?)", (c["profile"].lower(), user_id, user_name))
                out.append(self.checkout(cid))
        return out

    def rules(self) -> list[dict]:
        return self.q("SELECT * FROM rules ORDER BY profile")

    def forget_rule(self, profile: str) -> None:
        self.x("DELETE FROM rules WHERE profile=?", (profile.lower(),))

    def recent(self, n: int = 40) -> list[dict]:
        return self.q("SELECT * FROM checkouts ORDER BY ts DESC LIMIT ?", (n,))

    def skip(self, sender: str, ts: float) -> None:
        self.x("INSERT INTO skipped VALUES(?,1,?) ON CONFLICT(sender) DO UPDATE SET n=n+1, last_ts=?",
               (sender, ts, ts))

    # ---------------- drops ----------------
    def drops(self) -> list[dict]:
        """Newest first. Sent drops keep exactly the checkouts that were billed (counted in the database); the open
        checkouts are split by the 90-minute rule (key = "d" + id of its first checkout) and then joined by the
        runner's combines. Cached until the data changes."""
        return self._cached("drops", self._drops)

    def _drops(self) -> list[dict]:
        out = []
        for d in self.q("""SELECT b.key, b.sent_at, MIN(c.ts) AS first, MAX(c.ts) AS last,
                             SUM(c.cancelled=0) AS checkouts, SUM(CASE WHEN c.cancelled=0 THEN c.qty ELSE 0 END) AS units,
                             SUM(c.cancelled) AS cancelled,
                             COUNT(DISTINCT CASE WHEN c.cancelled=0 THEN c.user_id END) AS customers,
                             SUM(c.cancelled=0 AND c.user_id IS NULL) AS unassigned,
                             GROUP_CONCAT(DISTINCT CASE WHEN c.cancelled=0 THEN c.store END) AS stores
                           FROM bills b JOIN checkouts c ON c.billed=b.key GROUP BY b.key"""):
            out.append({**d, "parts": 1, "combined": False, "spans": [[d["first"], d["last"]]], "sent": True,
                        "stores": sorted((d["stores"] or "").split(",")) if d["stores"] else []})
        groups, parts, spans = self._open_groups()
        for k, rs in groups.items():
            counted = [r for r in rs if not r["cancelled"]]
            out.append({
                "key": k, "first": rs[0]["ts"], "last": rs[-1]["ts"],
                "parts": len(parts[k]), "combined": len(parts[k]) > 1, "spans": sorted(spans[k]),
                "sent": False, "sent_at": None,
                "checkouts": len(counted), "units": sum(r["qty"] for r in counted),
                "cancelled": len(rs) - len(counted),
                "customers": len({r["user_id"] for r in counted if r["user_id"]}),
                "unassigned": sum(1 for r in counted if not r["user_id"]),
                "stores": sorted({r["store"] for r in counted if r["store"]}),
            })
        out.sort(key=lambda d: -d["first"])
        return out

    def _open_groups(self):
        """Open (not billed) checkouts grouped into drops: (groups, parts, spans), each keyed by drop key."""
        def build():
            combos = {c["member"]: c["grp"] for c in self.q("SELECT * FROM combos")}
            groups: dict[str, list[dict]] = defaultdict(list)
            parts: dict[str, list[str]] = defaultdict(list)
            spans: dict[str, list[list[float]]] = defaultdict(list)
            for k, a in self._open_parts():
                g = combos.get(k, k)
                groups[g].extend(a)
                parts[g].append(k)
                spans[g].append([a[0]["ts"], a[-1]["ts"]])
            for rs in groups.values():
                rs.sort(key=lambda r: r["ts"])
            return groups, parts, spans
        return self._cached("open_groups", build)

    def open_drop_map(self) -> dict[str, str]:
        """checkout id -> drop key, for the open checkouts."""
        return self._cached("open_map", lambda: {r["id"]: k for k, rs in self._open_groups()[0].items() for r in rs})

    def drop_rows(self, key: str) -> list[dict]:
        if self.q("SELECT 1 FROM bills WHERE key=?", (key,)):
            return self.q("SELECT * FROM checkouts WHERE billed=? ORDER BY ts", (key,))
        return list(self._open_groups()[0].get(key, []))

    def _grp(self, member: str) -> str:
        r = self.q("SELECT grp FROM combos WHERE member=?", (member,))
        return r[0]["grp"] if r else member

    def _open_parts(self) -> list[tuple[str, list[dict]]]:
        out, cur = [], []
        for r in self.q("SELECT id, ts, qty, cancelled, user_id, user_name, store, product_key, product_name, image, "
                        "price, profile FROM checkouts WHERE billed IS NULL ORDER BY ts"):
            if cur and r["ts"] - cur[-1]["ts"] > DROP_GAP:
                out.append(("d" + cur[0]["id"], cur))
                cur = []
            cur.append(r)
        if cur:
            out.append(("d" + cur[0]["id"], cur))
        return out

    def combine(self, keys: list[str]) -> str:
        """Join drops into one. Only open drops that are next to each other among the open drops can be joined (a
        sent drop between them is skipped and stays separate). Sent drops can't be combined (already charged)."""
        sent = {b["key"] for b in self.q("SELECT key FROM bills")}
        if any(k in sent for k in keys):
            raise ValueError("A sent drop can't be combined: its customers were already charged.")
        keys = list(dict.fromkeys(keys))
        if len(keys) < 2:
            raise ValueError("Pick at least two drops that haven't been sent.")
        order = [d["key"] for d in sorted((d for d in self.drops() if not d["sent"]), key=lambda d: d["first"])]
        if any(k not in order for k in keys):
            raise ValueError("One of these drops no longer exists. Refresh and try again.")
        pos = sorted(order.index(k) for k in keys)
        if pos != list(range(pos[0], pos[0] + len(pos))):
            raise ValueError("Only drops next to each other can be combined.")
        with self.lock:
            members = [m["member"] for m in self.q(
                f"SELECT member FROM combos WHERE grp IN ({','.join('?' * len(keys))})", keys)]
            members = sorted(set(members) | set(keys), key=lambda m: self._first_ts(m))
            grp = members[0]
            for m in members:
                self.x("INSERT OR REPLACE INTO combos VALUES(?,?)", (m, grp))
        return grp

    def _first_ts(self, key: str) -> float:
        r = self.q("SELECT ts FROM checkouts WHERE id=?", (key[1:],))
        return r[0]["ts"] if r else 0

    def uncombine(self, key: str) -> None:
        if self.q("SELECT 1 FROM bills WHERE key=?", (key,)):
            raise ValueError("This drop was already sent, so it can't be split.")
        self.x("DELETE FROM combos WHERE grp=?", (key,))

    # ---------------- billed drops that change later ----------------
    def bill_lines(self, key: str, user_id: str) -> tuple[list[dict], float]:
        """A customer's lines and total for a billed drop, as it stands now (fees as used when it was sent)."""
        b = self.q("SELECT fees FROM bills WHERE key=?", (key,))
        fees = json.loads(b[0]["fees"]) if b else {}
        lines: dict[str, dict] = {}
        for r in self.q("SELECT * FROM checkouts WHERE billed=? AND user_id=? AND cancelled=0", (key, user_id)):
            ln = lines.setdefault(r["product_key"], {"key": r["product_key"], "name": r["product_name"],
                                                     "checkouts": 0, "units": 0, "fee": fees.get(r["product_key"], 0)})
            ln["checkouts"] += 1
            ln["units"] += r["qty"]
        out = sorted(lines.values(), key=lambda ln: ln["name"] or "")
        for ln in out:
            ln["subtotal"] = round(ln["fee"] * ln["units"], 2)
        return out, round(sum(ln["subtotal"] for ln in out), 2)

    def billed_amount(self, key: str, user_id: str) -> float:
        r = self.q("SELECT ROUND(COALESCE(SUM(amount),0),2) AS a FROM ledger WHERE bill=? AND user_id=? "
                   "AND kind IN ('charge','adjust')", (key, user_id))
        return r[0]["a"]

    def _rebill(self, key: str, user_id: str, user_name: str, note: str) -> None:
        lines, total = self.bill_lines(key, user_id)
        diff = round(total - self.billed_amount(key, user_id), 2)
        if abs(diff) > 0.004:
            self.x("INSERT INTO ledger(user_id,user_name,amount,kind,bill,ts,note) VALUES(?,?,?,?,?,?,?)",
                   (user_id, user_name, diff, "adjust", key, time.time(), note))
        m = self.message(key, user_id)
        if m and m["status"] != "sent":   # never delivered: the one message they get is simply the new one
            self.x("UPDATE messages SET total=?, lines=? WHERE bill=? AND user_id=?",
                   (total, json.dumps(lines), key, user_id))

    def queue_update(self, key: str, user_id: str) -> None:
        """Send this customer an updated summary for a drop whose bill changed after it was sent."""
        with self.lock:
            m = self.message(key, user_id)
            if not m:
                raise ValueError("This customer wasn't billed for this drop.")
            lines, total = self.bill_lines(key, user_id)
            if m["status"] == "sent":
                if abs(total - (m["total"] or 0)) < 0.005:
                    raise ValueError("Nothing changed since the last message.")
                self.x("UPDATE messages SET kind='update', prev_total=?, prev_lines=?, total=?, lines=?, "
                       "status='pending', error=NULL WHERE bill=? AND user_id=?",
                       (m["total"], m["lines"], total, json.dumps(lines), key, user_id))
            else:
                self.x("UPDATE messages SET total=?, lines=?, status='pending', error=NULL "
                       "WHERE bill=? AND user_id=?", (total, json.dumps(lines), key, user_id))

    def changed_unsent(self) -> list[dict]:
        """Delivered summaries whose bill changed since (an order was cancelled or made active again)."""
        out = []
        for m in self.q("SELECT bill, user_id, user_name, total FROM messages WHERE status='sent'"):
            now = self.billed_amount(m["bill"], m["user_id"])
            if abs(now - (m["total"] or 0)) > 0.004:
                out.append({**m, "now": now})
        return out

    # ---------------- reminders ----------------
    def open_bills(self, user_id: str, due_days: int, now: float | None = None) -> dict:
        """What a customer still owes, drop by drop. Payments pay off the oldest drop first."""
        now = now or time.time()
        bills = self.q("""SELECT b.key, b.sent_at, b.first_ts, b.last_ts, ROUND(SUM(l.amount),2) AS amount
                          FROM ledger l JOIN bills b ON b.key=l.bill
                          WHERE l.user_id=? AND l.kind IN ('charge','adjust') GROUP BY b.key ORDER BY b.sent_at""",
                       (user_id,))
        paid = -(self.q("SELECT COALESCE(SUM(amount),0) AS p FROM ledger WHERE user_id=? AND kind='payment'",
                        (user_id,))[0]["p"])
        left = paid
        out = []
        for b in bills:
            take = min(max(b["amount"], 0), left)
            left -= take
            open_ = round(b["amount"] - take, 2)
            due = b["sent_at"] + due_days * DAY if due_days else None
            if open_ > 0.004:
                out.append({**b, "open": open_, "due_ts": due, "overdue": bool(due and now > due)})
        name = self.q("SELECT user_name FROM ledger WHERE user_id=? ORDER BY ts DESC LIMIT 1", (user_id,))
        r = self.q("SELECT ts FROM reminders WHERE user_id=?", (user_id,))
        return {"user_id": user_id, "user_name": name[0]["user_name"] if name else "", "paid": round(paid, 2),
                "open": round(sum(b["open"] for b in out), 2), "bills": out,
                "last_reminded": r[0]["ts"] if r else None}

    def reminded(self, user_id: str, amount: float) -> None:
        self.x("INSERT OR REPLACE INTO reminders VALUES(?,?,?)", (user_id, time.time(), amount))

    def reminders(self) -> dict[str, float]:
        return {r["user_id"]: r["ts"] for r in self.q("SELECT * FROM reminders")}

    # ---------------- fees / summaries ----------------
    def last_fees(self) -> dict[str, float]:
        return {r["product_key"]: r["fee"] for r in self.q("SELECT * FROM fees")}

    def summary(self, key: str, fees: dict[str, float | None]) -> dict:
        """The fee table + one message per customer for a drop. Blocked until every product has a fee and every
        checkout belongs to someone, so nobody is billed short."""
        rows = self.drop_rows(key)
        bill = self.q("SELECT * FROM bills WHERE key=?", (key,))
        if bill:
            fees = json.loads(bill[0]["fees"])
        counted = [r for r in rows if not r["cancelled"]]
        products: dict[str, dict] = {}
        for r in counted:
            p = products.setdefault(r["product_key"], {"key": r["product_key"], "name": r["product_name"],
                                                       "store": r["store"], "image": r["image"],
                                                       "checkouts": 0, "units": 0, "price": r["price"]})
            p["checkouts"] += 1
            p["units"] += r["qty"]
        remembered = self.last_fees()
        for p in products.values():
            f = fees.get(p["key"]) if fees else None
            p["fee"] = f if f is not None else None
            p["last_fee"] = remembered.get(p["key"])
        per: dict[str, dict] = {}
        for r in counted:
            if not r["user_id"]:
                continue
            m = per.setdefault(r["user_id"], {"user_id": r["user_id"], "user_name": r["user_name"], "lines": {}})
            ln = m["lines"].setdefault(r["product_key"], {"key": r["product_key"], "name": r["product_name"],
                                                          "checkouts": 0, "units": 0})
            ln["checkouts"] += 1
            ln["units"] += r["qty"]
        customers = []
        for m in per.values():
            lines = []
            for ln in m["lines"].values():
                fee = products[ln["key"]]["fee"]
                lines.append({**ln, "fee": fee, "subtotal": None if fee is None else round(fee * ln["units"], 2)})
            lines.sort(key=lambda ln: ln["name"] or "")
            total = None if any(ln["subtotal"] is None for ln in lines) else round(sum(ln["subtotal"] for ln in lines), 2)
            customers.append({"user_id": m["user_id"], "user_name": m["user_name"], "lines": lines, "total": total})
        msgs = {m["user_id"]: m for m in self.q("SELECT * FROM messages WHERE bill=?", (key,))}
        have = {c["user_id"] for c in customers}
        for uid, m in msgs.items():   # billed, but every order of theirs was cancelled since: now $0
            if uid not in have:
                customers.append({"user_id": uid, "user_name": m["user_name"], "lines": [], "total": 0})
        customers.sort(key=lambda c: (c["user_name"] or "").lower())
        for c in customers:
            c["cancelled"] = sum(1 for r in rows if r["cancelled"] and r["user_id"] == c["user_id"])
            m = msgs.get(c["user_id"])
            if m:
                c.update(status=m["status"], error=m["error"], kind=m["kind"] or "summary", sent_total=m["total"],
                         prev_total=m["prev_total"], prev_lines=json.loads(m["prev_lines"]) if m["prev_lines"] else None,
                         changed=m["status"] == "sent" and abs((c["total"] or 0) - (m["total"] or 0)) > 0.004)
        blockers = []
        missing = [p["name"] for p in products.values() if p["fee"] is None]
        if missing:
            blockers.append(f"Set a fee for {len(missing)} product{'s' * (len(missing) != 1)}")
        un = sum(1 for r in counted if not r["user_id"])
        if un:
            blockers.append(f"Assign {un} checkout{'s' * (un != 1)} to a customer")
        if not customers and not un:
            blockers.append("No checkouts in this drop")
        return {"key": key, "rows": rows, "products": sorted(products.values(), key=lambda p: -p["units"]),
                "customers": customers, "blockers": blockers, "sent": bool(bill),
                "sent_at": bill[0]["sent_at"] if bill else None,
                "grand_total": round(sum(c["total"] or 0 for c in customers), 2)}

    def bill(self, key: str, fees: dict[str, float]) -> dict:
        """Lock the drop, charge each customer and queue their DM (the bot sends them)."""
        with self.batch():
            if self.q("SELECT 1 FROM bills WHERE key=?", (key,)):
                raise ValueError("This drop was already sent.")
            s = self.summary(key, fees)
            if s["blockers"]:
                raise ValueError(". ".join(s["blockers"]))
            rows = [r for r in s["rows"]]
            now = time.time()
            ids = [r["id"] for r in rows]
            self.x("UPDATE checkouts SET billed=? WHERE id IN (SELECT value FROM json_each(?))", (key, json.dumps(ids)))
            self.x("DELETE FROM combos WHERE grp=?", (key,))
            used = {p["key"]: p["fee"] for p in s["products"]}
            self.x("INSERT INTO bills VALUES(?,?,?,?,?)", (key, now, rows[0]["ts"], rows[-1]["ts"], json.dumps(used)))
            for k, f in used.items():
                self.x("INSERT OR REPLACE INTO fees VALUES(?,?)", (k, f))
            for c in s["customers"]:
                self.x("INSERT INTO messages(bill,user_id,user_name,total,lines,status) VALUES(?,?,?,?,?,'pending')",
                       (key, c["user_id"], c["user_name"], c["total"], json.dumps(c["lines"])))
                self.x("INSERT INTO ledger(user_id,user_name,amount,kind,bill,ts,note) VALUES(?,?,?,?,?,?,?)",
                       (c["user_id"], c["user_name"], c["total"], "charge", key, now, None))
        return self.summary(key, {})

    def message_data(self, m: dict) -> dict:
        """A messages row -> what messages.fee_message needs."""
        n = self.q("SELECT COUNT(*) AS n FROM checkouts WHERE billed=? AND user_id=? AND cancelled=1",
                   (m["bill"], m["user_id"]))[0]["n"]
        return {"user_id": m["user_id"], "kind": m.get("kind") or "summary", "total": m["total"],
                "lines": json.loads(m["lines"]) if m["lines"] else [], "prev_total": m.get("prev_total"),
                "prev_lines": json.loads(m["prev_lines"]) if m.get("prev_lines") else None,
                "first_ts": m["first_ts"], "last_ts": m["last_ts"], "sent_at": m["bill_sent"], "cancelled": n}

    def pending_messages(self, key: str | None = None) -> list[dict]:
        sql = "SELECT m.*, b.first_ts, b.last_ts, b.sent_at AS bill_sent FROM messages m JOIN bills b ON b.key=m.bill WHERE m.status='pending'"
        return self.q(sql + (" AND m.bill=?" if key else ""), (key,) if key else ())

    def message_result(self, bill: str, user_id: str, ok: bool, error: str | None = None) -> None:
        self.x("UPDATE messages SET status=?, error=?, sent_at=? WHERE bill=? AND user_id=?",
               ("sent" if ok else "failed", error, time.time() if ok else None, bill, user_id))

    def retry(self, key: str) -> int:
        return self.x("UPDATE messages SET status='pending', error=NULL WHERE bill=? AND status='failed'", (key,))

    def message(self, bill: str, user_id: str) -> dict | None:
        r = self.q("SELECT m.*, b.first_ts, b.last_ts, b.sent_at AS bill_sent FROM messages m JOIN bills b ON b.key=m.bill "
                   "WHERE m.bill=? AND m.user_id=?", (bill, user_id))
        return r[0] if r else None

    # ---------------- ledger ----------------
    def balances(self) -> list[dict]:
        rows = self.q("""SELECT user_id, MAX(user_name) AS user_name,
                           ROUND(SUM(CASE WHEN kind IN ('charge','adjust') THEN amount ELSE 0 END),2) AS charged,
                           ROUND(-SUM(CASE WHEN kind='payment' THEN amount ELSE 0 END),2) AS paid,
                           ROUND(SUM(amount),2) AS owed, MAX(ts) AS last_ts,
                           SUM(CASE WHEN kind='charge' THEN 1 ELSE 0 END) AS drops
                         FROM ledger GROUP BY user_id ORDER BY owed DESC, user_name""")
        return rows

    def history(self, user_id: str | None = None, n: int = 200) -> list[dict]:
        if user_id:
            return self.q("SELECT * FROM ledger WHERE user_id=? ORDER BY ts DESC LIMIT ?", (user_id, n))
        return self.q("SELECT * FROM ledger ORDER BY ts DESC LIMIT ?", (n,))

    def pay(self, user_id: str, amount: float | None, note: str | None) -> float:
        """Record a payment. amount None = everything owed."""
        with self.lock:
            b = next((r for r in self.balances() if r["user_id"] == user_id), None)
            if not b:
                raise ValueError("No charges for this customer.")
            amt = round(b["owed"] if amount is None else float(amount), 2)
            if amt <= 0:
                raise ValueError("Nothing to mark as paid.")
            self.x("INSERT INTO ledger(user_id,user_name,amount,kind,bill,ts,note) VALUES(?,?,?,?,?,?,?)",
                   (user_id, b["user_name"], -amt, "payment", None, time.time(), (note or "")[:200] or None))
            return amt

    def undo_payment(self, entry_id: int) -> None:
        self.x("DELETE FROM ledger WHERE id=? AND kind='payment'", (entry_id,))
