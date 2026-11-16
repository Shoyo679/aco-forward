"""ACO Forward: tags each checkout's customer (from the profile name) and bills them per drop. Tray app + dashboard.

    .venv\\Scripts\\pythonw aco_forward.py            open the window (or show the running copy)
    .venv\\Scripts\\pythonw aco_forward.py --tray     start in the tray (used by Start with Windows)
    .venv\\Scripts\\python  aco_forward.py --install-shortcuts
    .venv\\Scripts\\python  aco_forward.py --demo     made-up data in demo-data/, no Discord (for trying it out)
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import messages  # noqa: E402
import secret  # noqa: E402
import upkeep  # noqa: E402
from store import Store  # noqa: E402
from version import UPDATE_URL, VERSION  # noqa: E402

TITLE = "ACO Forward"
APP_ID = "Shoyo.ACOForward"
DEMO = "--demo" in sys.argv
UI_PORT, SIGNAL_PORT = (8888, 8887) if DEMO else (8788, 8787)
if "--ports" in sys.argv:
    UI_PORT, SIGNAL_PORT = (int(p) for p in sys.argv[sys.argv.index("--ports") + 1].split(","))
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Data lives outside the program folder, so a new version can be unzipped over (or next to) the old one safely.
DATA = (Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv
        else ROOT / "demo-data" if DEMO else upkeep.home_dir())
CONFIG_FILE = DATA / "config.json"
LOG_FILE = DATA / "aco-forward.log"


def log(text: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}\n")


def _desktop() -> Path:
    od = os.environ.get("OneDrive")
    if od and (Path(od) / "Desktop").is_dir():
        return Path(od) / "Desktop"
    return Path(os.environ["USERPROFILE"]) / "Desktop"


# ---------------- config ----------------
DEFAULTS = {"sources": [], "output": None, "names": {}, "token": None, "tour_done": False,
            "pay_note": "", "due_days": 2}   # fee messages: your payment note, due N days after (0 = no due date)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def order_key() -> bytes:
    """Secret for the one-way order-number codes (data/order.key, made once)."""
    f = DATA / "order.key"
    if not f.exists():
        f.write_bytes(secrets.token_bytes(32))
    return f.read_bytes()


# ---------------- start with Windows ----------------
def start_with_windows() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, TITLE)
            return True
    except OSError:
        return False


def set_start_with_windows(on: bool) -> None:
    import winreg
    pyw = Path(sys.executable).with_name("pythonw.exe")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, TITLE, 0, winreg.REG_SZ,
                              f'"{pyw if pyw.exists() else sys.executable}" "{ROOT / "aco_forward.py"}" --tray')
        else:
            try:
                winreg.DeleteValue(k, TITLE)
            except OSError:
                pass


# ---------------- icon ----------------
BADGE = (88, 101, 242)   # Discord blurple: the @ tag badge


def make_icon(dot=None, size: int = 256):
    """A monkey (owner's pick, Nov 16 2026) on an orange disc, with an @ badge (tagging) bottom-right; the badge
    shows the status colour in the tray."""
    from PIL import Image, ImageDraw, ImageFont
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for i in range(S):
        t = i / S
        gd.line([(0, i), (S, i)], fill=(int(255 - 15 * t), int(170 - 60 * t), int(70 - 20 * t)))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([8, 8, S - 8, S - 8], fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    fur, fur2, face, ink = (92, 52, 28), (120, 72, 40), (246, 208, 160), (34, 20, 12)
    cx, cy = 482, 520
    # ears
    for ex in (cx - 300, cx + 300):
        d.ellipse([ex - 120, cy - 150, ex + 120, cy + 90], fill=fur)
        d.ellipse([ex - 70, cy - 100, ex + 70, cy + 40], fill=face)
    # head + tuft
    d.ellipse([cx - 255, cy - 260, cx + 255, cy + 250], fill=fur)
    d.polygon([(cx - 40, cy - 250), (cx + 10, cy - 330), (cx + 30, cy - 245)], fill=fur)
    d.polygon([(cx + 10, cy - 250), (cx + 80, cy - 310), (cx + 75, cy - 235)], fill=fur2)
    # face mask: two eye lobes + muzzle
    d.ellipse([cx - 190, cy - 170, cx + 10, cy + 40], fill=face)
    d.ellipse([cx - 10, cy - 170, cx + 190, cy + 40], fill=face)
    d.ellipse([cx - 200, cy - 20, cx + 200, cy + 225], fill=face)
    # eyes
    for ex in (cx - 85, cx + 85):
        d.ellipse([ex - 38, cy - 95, ex + 38, cy - 5], fill=ink)
        d.ellipse([ex - 8, cy - 80, ex + 14, cy - 58], fill=(255, 255, 255))
    # nose + smile
    d.ellipse([cx - 42, cy + 40, cx - 14, cy + 66], fill=fur)
    d.ellipse([cx + 14, cy + 40, cx + 42, cy + 66], fill=fur)
    d.arc([cx - 105, cy + 30, cx + 105, cy + 175], start=20, end=160, fill=ink, width=22)
    # @ badge
    col = tuple(dot) if dot else BADGE
    bx, by, r = 838, 838, 152
    d.ellipse([bx - r - 30, by - r - 30, bx + r + 30, by + r + 30], fill=(14, 17, 23))
    d.ellipse([bx - r, by - r, bx + r, by + r], fill=col)
    try:
        font = ImageFont.truetype("seguisb.ttf", 230)
    except OSError:
        font = ImageFont.load_default()
    d.text((bx, by - 8), "@", font=font, fill=(255, 255, 255), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


DOTS = {"online": (35, 165, 90), "connecting": (56, 189, 248), "no_token": (240, 178, 50),
        "bad_token": (242, 63, 67), "intents": (242, 63, 67), "offline": (107, 116, 132)}


# ---------------- app ----------------
class App:
    def __init__(self) -> None:
        DATA.mkdir(parents=True, exist_ok=True)
        self.cfg = load_config()
        save_config(self.cfg)
        saved = upkeep.backup_before_upgrade(DATA / "forward.db", DATA, VERSION)
        self.store = Store(DATA / "forward.db")
        if saved:
            log(f"version {VERSION}: database copied to {saved.name} before upgrading")
        self.store.set_meta("app_version", VERSION)
        self.update: dict | None = None      # newer version info, from the update check
        self.subs: list[queue.Queue] = []
        if DEMO:
            import demo
            self.bot = demo.FakeForwarder(self.store, lambda: self.cfg, self.broadcast)
            demo.seed(self.store, self.cfg, self.bot)
            save_config(self.cfg)
        else:
            from bot import Forwarder
            self.bot = Forwarder(self.store, lambda: self.cfg, self.broadcast, order_key(), log)
        self.window = self.tray = None
        self.quitting = False
        self._last_dot = None

    def check_update(self) -> dict | None:
        info = upkeep.fetch_latest(UPDATE_URL)
        self.update = info if info and upkeep.newer(info["version"], VERSION) else None
        self.broadcast("state")
        return info

    def update_loop(self) -> None:
        while not self.quitting:
            self.check_update()
            for _ in range(6 * 3600):
                if self.quitting:
                    return
                time.sleep(1)

    def token(self) -> str | None:
        try:
            return secret.unprotect(self.cfg["token"]) if self.cfg.get("token") else None
        except OSError:
            return None

    def broadcast(self, what: str) -> None:
        for q in list(self.subs):
            try:
                q.put_nowait(what)
            except queue.Full:
                pass
        if what == "state":
            self.update_tray()

    # ---- snapshot for the dashboard ----
    def snapshot(self) -> dict:
        st = self.store
        now = datetime.now()
        midnight = datetime(now.year, now.month, now.day).timestamp()
        today = st.q("SELECT * FROM checkouts WHERE ts>=? AND cancelled=0", (midnight,))
        week = st.q("SELECT ts FROM checkouts WHERE ts>=? AND cancelled=0", (midnight - 6 * 86400,))
        days = [0] * 7
        for r in week:
            days[min(6, int((r["ts"] - (midnight - 6 * 86400)) // 86400))] += 1
        needs = st.unmatched()
        bal = st.balances()
        drops = st.drops()
        cols = ("id, ts, store, bot, product_name, qty, profile, tag, problem, user_id, user_name, how, cancelled, "
                "cancel_by, billed, image, order_number, source")
        rows = st.q(f"SELECT {cols} FROM checkouts ORDER BY ts DESC LIMIT 12")   # Home's live feed
        reminded = st.reminders()
        for b in bal:
            info = st.open_bills(b["user_id"], self.cfg.get("due_days", 0)) if (b["owed"] or 0) > 0.004 else None
            b["overdue"] = bool(info and any(x["overdue"] for x in info["bills"]))
            b["reminded"] = reminded.get(b["user_id"])
        open_drops = [d for d in drops if not d["sent"]]
        last_ck = st.q("SELECT MAX(ts) AS t FROM checkouts")[0]["t"]
        upd = self.update if self.update and self.update["version"] != self.cfg.get("dismissed_update") else None
        return {
            "demo": DEMO, "version": VERSION, "update": upd, "update_configured": bool(UPDATE_URL),
            "data_dir": str(DATA),
            "status": {"state": self.bot.state, "error": self.bot.error, "me": self.bot.me, "last_checkout": last_ck,
                       "members": len(self.bot.members)},
            "health": self.bot.channel_health(),
            "setup": {"token_saved": bool(self.cfg.get("token")), "sources": self.cfg["sources"],
                      "output": self.cfg["output"], "names": self.cfg.get("names", {}),
                      "start_with_windows": start_with_windows(), "tour_done": self.cfg.get("tour_done", False),
                      "pay_note": self.cfg.get("pay_note", ""), "due_days": self.cfg.get("due_days", 0)},
            "stats": {"today": len(today), "today_units": sum(r["qty"] for r in today),
                      "today_tagged": sum(1 for r in today if r["user_id"]),
                      "needs": len(needs), "owed": round(sum(max(0, b["owed"] or 0) for b in bal), 2),
                      "owing": sum(1 for b in bal if (b["owed"] or 0) > 0.004),
                      "open_drops": len(open_drops), "week": days,
                      "customers_today": len({r["user_id"] for r in today if r["user_id"]})},
            "rows": rows, "needs_rows": needs[:500], "drops": drops, "balances": bal,
            "posting": st.post_backlog(),
            "rules": st.rules(),
            "skipped": st.q("SELECT * FROM skipped ORDER BY last_ts DESC LIMIT 20"),
            "failed_dms": st.q("SELECT bill, user_name, error FROM messages WHERE status='failed'"),
            "changed": st.changed_unsent(),
            "progress": {"token": bool(self.cfg.get("token")), "online": self.bot.state == "online",
                         "channels": bool(self.cfg["sources"] and self.cfg["output"]),
                         "checkout": last_ck is not None,
                         "sent": bool(st.q("SELECT 1 FROM bills LIMIT 1"))},
        }

    def with_previews(self, s: dict) -> dict:
        """Add the exact message each customer gets (or got, or would get as an update) to a drop summary."""
        rows = s["rows"]
        first, last = (rows[0]["ts"], rows[-1]["ts"]) if rows else (time.time(), time.time())
        for c in s["customers"]:
            m = self.store.message(s["key"], c["user_id"]) if s["sent"] else None
            if not m:
                data = {"user_id": c["user_id"], "kind": "summary", "total": c["total"], "lines": c["lines"],
                        "first_ts": first, "last_ts": last, "sent_at": time.time()}
            elif c.get("changed"):
                data = {**self.store.message_data(m), "kind": "update", "prev_total": m["total"],
                        "prev_lines": json.loads(m["lines"]) if m["lines"] else [], "total": c["total"],
                        "lines": c["lines"]}
            else:
                data = self.store.message_data(m)
            c["msg"] = messages.fee_message(data, self.cfg) if c["total"] is not None else None
        return s

    # ---- tray ----
    def update_tray(self) -> None:
        if not self.tray:
            return
        st = self.bot.state
        if st != self._last_dot:
            self._last_dot = st
            self.tray.icon = make_icon(DOTS.get(st), 64)
            self.tray.title = f"{TITLE}: {st.replace('_', ' ')}"

    def start_tray(self) -> None:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda i, it: self.show(), default=True),
            pystray.MenuItem("Reconnect bot", lambda i, it: threading.Thread(target=self.reconnect).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Quit {TITLE}", lambda i, it: threading.Thread(target=self.quit).start()),
        )
        self.tray = pystray.Icon("aco-forward", make_icon(DOTS.get(self.bot.state), 64), TITLE, menu)
        threading.Thread(target=self.tray.run, name="tray", daemon=True).start()

    def reconnect(self) -> None:
        self.bot.start(self.token())

    # ---- window ----
    def show(self) -> None:
        if self.window:
            self.window.show()
            self.window.restore()

    def on_closing(self) -> bool:
        if self.quitting:
            return True
        self.window.hide()
        return False

    def quit(self) -> None:
        """Window and tray icon go away at once; Discord then gets at most 3 seconds to disconnect. Nothing is lost
        if it doesn't answer: data is saved as it arrives, and queued posts / DMs are sent at the next start."""
        self.quitting = True
        t0 = time.perf_counter()
        if self.window:
            self.window.hide()
        if self.tray:
            self.tray.stop()
        stopper = threading.Thread(target=self.bot.stop, kwargs={"timeout": 3}, name="bot-stop", daemon=True)
        stopper.start()
        stopper.join(3.5)
        took = time.perf_counter() - t0
        log(f"quit: Discord disconnected in {took:.1f} s" if not stopper.is_alive()
            else f"quit: Discord didn't answer within {took:.1f} s; closed anyway")
        self._quit_done = True
        if self.window:
            self.window.destroy()

    def run(self, hidden: bool, headless: bool = False) -> None:
        sig = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sig.bind(("127.0.0.1", SIGNAL_PORT))
        sig.listen()

        def listen() -> None:
            while not self.quitting:
                try:
                    conn, _ = sig.accept()
                    conn.close()
                    self.show()
                except OSError:
                    return
        threading.Thread(target=listen, daemon=True).start()
        http = ThreadingHTTPServer(("127.0.0.1", UI_PORT), make_handler(self))
        http.daemon_threads = True
        threading.Thread(target=http.serve_forever, daemon=True).start()
        self.bot.start(self.token())
        if not DEMO and start_with_windows():
            set_start_with_windows(True)   # points at this copy, even if a new version was unzipped elsewhere
        if not DEMO:
            threading.Thread(target=self.update_loop, name="update-check", daemon=True).start()
        if headless:   # --serve: dashboard only, for checking in a browser
            print(f"http://127.0.0.1:{UI_PORT}/")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return
        import webview
        self.start_tray()
        ico = ROOT / "icon.ico"
        self.window = webview.create_window(TITLE + (" (demo)" if DEMO else ""), f"http://127.0.0.1:{UI_PORT}/",
                                            width=1440, height=920, min_size=(1000, 640), hidden=hidden,
                                            background_color="#0d0f14")
        self.window.events.closing += self.on_closing
        webview.start(icon=str(ico) if ico.exists() else None, private_mode=True)
        self.quitting = True
        if not getattr(self, "_quit_done", False):   # quit() already stopped the bot (with its 3 s limit)
            self.bot.stop(timeout=3)
        http.shutdown()
        sig.close()


def make_handler(app: App):
    ui = ROOT / "ui"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def _same_origin(self) -> bool:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            ok = (f"127.0.0.1:{UI_PORT}", f"localhost:{UI_PORT}")
            return host in ok and (origin is None or origin in tuple("http://" + o for o in ok))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _err(self, text: str, code: int = 400) -> None:
            self._json({"error": text}, code)

        def do_GET(self) -> None:
            if not self._same_origin():
                return self._send(403, b"forbidden", "text/plain")
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path
            if p == "/":
                return self._send(200, (ui / "index.html").read_bytes(), "text/html; charset=utf-8")
            if p in ("/logo.png",) and (ROOT / "logo.png").exists():
                return self._send(200, (ROOT / "logo.png").read_bytes(), "image/png")
            if p == "/guide.md":
                return self._send(200, (ROOT / "GUIDE.md").read_bytes(), "text/plain; charset=utf-8")
            if p == "/api/state":
                return self._json(app.snapshot())
            if p == "/api/servers":
                return self._json(app.bot.servers())
            if p == "/api/members":
                return self._json(app.bot.member_search(qs.get("q", "")))
            if p == "/api/history":
                return self._json(app.store.history(qs.get("user_id")))
            if p == "/api/checkouts":
                return self._json(app.store.checkouts_page(
                    qs.get("drop") or None, qs.get("user") or None, qs.get("status") or None, qs.get("q") or None,
                    max(0, int(qs.get("offset", 0) or 0)), min(200, int(qs.get("limit", 100) or 100))))
            if p == "/api/products":
                return self._json([r["product_name"] for r in app.store.q(
                    "SELECT product_name, MAX(ts) AS t FROM checkouts GROUP BY lower(product_name) ORDER BY t DESC LIMIT 300")])
            if p == "/api/reminder":
                info = app.store.open_bills(qs.get("user_id", ""), app.cfg.get("due_days", 0))
                return self._json({**info, "msg": messages.reminder_message(info, app.cfg)})
            if p == "/api/stream":
                q: queue.Queue = queue.Queue(maxsize=200)
                app.subs.append(q)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    while not app.quitting:
                        try:
                            self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    app.subs.remove(q)
                return
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            if not self._same_origin():
                return self._send(403, b"forbidden", "text/plain")
            n = int(self.headers.get("Content-Length") or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                b = {}
            p, st = self.path, app.store
            try:
                if p == "/api/token":
                    tok = str(b.get("token", "")).strip().strip('"')
                    if len(tok) < 50 or " " in tok:
                        return self._err("That doesn't look like a bot token. Copy it from Bot → Reset Token.")
                    app.cfg["token"] = secret.protect(tok)
                    save_config(app.cfg)
                    threading.Thread(target=app.reconnect, daemon=True).start()
                    return self._json({"ok": True})
                if p == "/api/token/clear":
                    app.cfg["token"] = None
                    save_config(app.cfg)
                    threading.Thread(target=app.bot.stop, daemon=True).start()
                    app.bot.state = "no_token"
                    app.broadcast("state")
                    return self._json({"ok": True})
                if p == "/api/reconnect":
                    threading.Thread(target=app.reconnect, daemon=True).start()
                    return self._json({"ok": True})
                if p == "/api/channels":
                    src = [str(c) for c in b.get("sources", [])][:50]
                    out = str(b["output"]) if b.get("output") else None
                    if out and out in src:
                        return self._err("The output channel can't also be a source channel.")
                    app.cfg.update(sources=src, output=out,
                                   names={str(k): str(v)[:120] for k, v in (b.get("names") or {}).items()})
                    save_config(app.cfg)
                    app.broadcast("state")
                    return self._json({"ok": True})
                if p == "/api/assign":
                    rows = st.assign([str(i) for i in b.get("ids", [])], str(b["user_id"]), str(b["user_name"]),
                                     bool(b.get("remember")))
                    app.bot.repost(rows)
                    app.broadcast("data")
                    return self._json({"assigned": len(rows)})
                if p == "/api/forget-rule":
                    st.forget_rule(str(b.get("profile", "")))
                    return self._json({"ok": True})
                if p == "/api/combine":
                    key = st.combine([str(k) for k in b.get("keys", [])])
                    app.broadcast("data")
                    return self._json({"key": key})
                if p == "/api/uncombine":
                    st.uncombine(str(b.get("key")))
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/summary":
                    return self._json(app.with_previews(st.summary(str(b.get("key")), _fees(b))))
                if p == "/api/send":
                    s = st.bill(str(b.get("key")), _fees(b))
                    app.bot.send_pending(s["key"])
                    app.broadcast("data")
                    return self._json(app.with_previews(s))
                if p == "/api/add-checkout":
                    if not b.get("user_id"):
                        return self._err("Pick the customer.")
                    ts = float(b.get("ts") or time.time())
                    c = st.add_manual(str(b["user_id"]), str(b.get("user_name") or ""), str(b.get("product") or ""),
                                      int(b.get("qty") or 1), b.get("order"), ts, order_key(),
                                      post=bool(app.cfg.get("output")))
                    app.bot.kick()
                    app.broadcast("data")
                    sent = st.q("SELECT 1 FROM bills b JOIN checkouts c ON c.billed=b.key WHERE c.id=?", (c["id"],))
                    return self._json({"ok": True, "drop": st.open_drop_map().get(c["id"]), "late": bool(sent)})
                if p == "/api/status":
                    row = st.set_status(str(b.get("id")), bool(b.get("cancelled")), "you")
                    if not row:
                        return self._err("That checkout no longer exists.")
                    app.bot.repost([row])
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/update":
                    st.queue_update(str(b.get("key")), str(b.get("user_id")))
                    app.bot.send_pending(str(b.get("key")))
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/remind":
                    info = st.open_bills(str(b.get("user_id")), app.cfg.get("due_days", 0))
                    if info["open"] <= 0.004:
                        return self._err("They don't owe anything.")
                    if app.bot.state != "online":
                        return self._err("The bot is offline, so the reminder can't be sent right now.")
                    app.bot.send_reminder(info["user_id"], messages.reminder_message(info, app.cfg))
                    st.reminded(info["user_id"], info["open"])
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/retry":
                    st.retry(str(b.get("key")))
                    app.bot.send_pending(str(b.get("key")))
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/pay":
                    amt = b.get("amount")
                    paid = st.pay(str(b.get("user_id")), None if amt in (None, "") else float(amt), b.get("note"))
                    app.broadcast("data")
                    return self._json({"paid": paid})
                if p == "/api/undo-pay":
                    st.undo_payment(int(b.get("id")))
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/test-post":
                    return self._json({"result": app.bot.test_post()})
                if p == "/api/config":
                    if "start_with_windows" in b:
                        set_start_with_windows(bool(b["start_with_windows"]))
                    if "tour_done" in b:
                        app.cfg["tour_done"] = bool(b["tour_done"])
                    if "pay_note" in b:
                        app.cfg["pay_note"] = str(b["pay_note"] or "")[:500]
                    if "due_days" in b:
                        d = int(b["due_days"] or 0)
                        if not 0 <= d <= 60:
                            return self._err("Due days must be between 0 and 60.")
                        app.cfg["due_days"] = d
                    save_config(app.cfg)
                    app.broadcast("data")
                    return self._json({"ok": True})
                if p == "/api/check-update":
                    info = app.check_update()
                    return self._json({"current": VERSION, "configured": bool(UPDATE_URL), "latest": info,
                                       "newer": bool(app.update)})
                if p == "/api/dismiss-update":
                    app.cfg["dismissed_update"] = str(b.get("version") or "")
                    save_config(app.cfg)
                    app.broadcast("state")
                    return self._json({"ok": True})
                if p == "/api/open-link":
                    url = str(b.get("url") or "")
                    if url.startswith("https://") and url in (ROOT / "GUIDE.md").read_text(encoding="utf-8"):
                        os.startfile(url)   # only links written in the guide
                    return self._json({"ok": True})
                if p == "/api/open-release":
                    if app.update and app.update.get("url"):   # only the link from the update file
                        os.startfile(app.update["url"])
                    return self._json({"ok": True})
                if p == "/api/open-folder":
                    os.startfile(DATA)
                    return self._json({"ok": True})
                if p == "/api/hide":
                    if app.window:
                        app.window.hide()
                    return self._json({"ok": True})
            except (ValueError, RuntimeError, KeyError) as e:
                return self._err(str(e) or "Something was missing.")
            self._send(404, b"not found", "text/plain")

    return H


def _fees(b: dict) -> dict:
    out = {}
    for k, v in (b.get("fees") or {}).items():
        if v in (None, ""):
            continue
        f = float(v)
        if f < 0:
            raise ValueError("Fees can't be negative.")
        out[str(k)] = round(f, 2)
    return out


def install_shortcuts() -> None:
    import hashlib
    import shutil
    ico = ROOT / "icon.ico"
    img = make_icon(None, 256)
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(ROOT / "logo.png")
    (ROOT / "icons").mkdir(exist_ok=True)
    for old in (ROOT / "icons").glob("fwd-*.ico"):
        old.unlink()
    lnk_ico = ROOT / "icons" / f"fwd-{hashlib.sha256(ico.read_bytes()).hexdigest()[:8]}.ico"
    shutil.copyfile(ico, lnk_ico)
    pyw = Path(sys.executable).with_name("pythonw.exe")
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    for folder in (_desktop(), start_menu):
        link = folder / f"{TITLE}.lnk"
        script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
                  f"$s.TargetPath='{pyw}';$s.Arguments='\"{ROOT / 'aco_forward.py'}\"';"
                  f"$s.WorkingDirectory='{ROOT}';$s.IconLocation='{lnk_ico}';"
                  f"$s.Description='Tags ACO checkouts and bills customers per drop';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=0x08000000)
        print(f"Shortcut: {link}")


def main() -> int:
    if "--install-shortcuts" in sys.argv:
        install_shortcuts()
        return 0
    try:
        with socket.create_connection(("127.0.0.1", SIGNAL_PORT), timeout=1):
            return 0   # already running: it shows its window
    except OSError:
        pass
    if not DEMO and "--data" not in sys.argv and upkeep.move_old_data(ROOT / "data", DATA):
        print(f"Moved the data folder to {DATA}")
    DATA.mkdir(parents=True, exist_ok=True)
    if sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    App().run(hidden="--tray" in sys.argv, headless="--serve" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
