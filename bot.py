"""The runner's own Discord bot: reads checkouts in the source channels, tags the customer in the output channel and
sends each customer their checkout summary by DM. Runs in its own thread with its own asyncio loop; the dashboard
calls it through run() / the plain methods below.

The tagged post shows only the tag and four lines: Product, Site, Qty and Profile (a spoiler: click to reveal), plus
the product picture (owner, Nov 16 2026; Site + spoiler in 1.0.1). Never the checkout bot, price, account, email,
proxy or order number, and no footer.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime

import discord

import messages
import parse

GREEN, AMBER, RED = 0x23A55A, 0xF0B232, 0xF23F43


def message_record(m: discord.Message) -> dict:
    return {"id": str(m.id), "ts": m.created_at.timestamp(), "channel_id": str(m.channel.id),
            "guild_id": str(m.guild.id) if m.guild else None, "source_name": m.author.name,
            "jump_url": m.jump_url, "embeds": [e.to_dict() for e in m.embeds]}


def _spoiler(text: str | None, code: bool = False) -> str:
    """Hidden until clicked. "|" would end the spoiler early, so it's removed."""
    t = (text or "").replace("|", "").replace("`", "").strip()
    if not t:
        return "—"
    return f"||`{t}`||" if code else f"||{discord.utils.escape_markdown(t)}||"


def post_text(c: dict) -> str:
    """Product / Site / Qty / Profile, one "Label: value" line each."""
    esc = discord.utils.escape_markdown
    return "\n".join([f"**Product:** {esc((c['product_name'] or 'Unknown product')[:300])}",
                      f"**Site:** {esc(c.get('store') or '—')}",
                      f"**Qty:** {c['qty']}",
                      f"**Profile:** {_spoiler((c['profile'] or '')[:100])}"])


def post_parts(c: dict) -> tuple[str, discord.Embed]:
    """The tagged copy of a checkout in the output channel."""
    if c["cancelled"]:
        colour, title = RED, "Order cancelled"
    elif c["user_id"]:
        colour, title = GREEN, "Checked out"
    else:
        colour, title = AMBER, "Checked out"
    if c["user_id"]:
        content = f"<@{c['user_id']}> checked out" if not c["cancelled"] else f"~~<@{c['user_id']}> checked out~~"
    else:
        why = c["problem"] or "no member has that username"
        content = f"⚠️ Unassigned: profile {_spoiler((c['profile'] or 'none')[:60], code=True)}: {why.lower()}"
    e = discord.Embed(title=title, colour=colour, description=post_text(c))
    if c["image"]:
        e.set_thumbnail(url=c["image"])
    return content, e


GROUP = 10   # Discord allows 10 embeds in one message


def post_batch_parts(rows: list[dict]) -> tuple[str, list[discord.Embed]]:
    """One tagged message for several checkouts (used when posts pile up during a big drop: one channel only takes
    about 5 messages per 5 seconds). One line tags everyone, then one card per checkout."""
    if len(rows) == 1:
        content, e = post_parts(rows[0])
        return content, [e]
    tags = list(dict.fromkeys(f"<@{c['user_id']}>" for c in rows if c["user_id"] and not c["cancelled"]))
    un = sum(1 for c in rows if not c["user_id"])
    content = (" ".join(tags) + " checked out") if tags else "Checked out"
    if un:
        content += f"\n⚠️ {un} unassigned (profile name matches no one)"
    embeds = []
    for c in rows[:GROUP]:
        e = post_parts(c)[1]
        who = f"@{c['user_name']}" if c["user_id"] else "⚠️ Unassigned"
        e.title = f"{e.title} · {who}"
        embeds.append(e)
    return content, embeds


def to_embed(msg: dict) -> tuple[str, discord.Embed]:
    """A message from messages.py -> what Discord gets."""
    e = discord.Embed(title=msg["title"], colour=msg["color"], description=msg["description"][:4000])
    for f in msg["fields"]:
        e.add_field(name=f["name"], value=f["value"], inline=False)
    e.set_footer(text=msg["footer"])
    return msg["content"], e


class Forwarder:
    """state: no_token / connecting / online / bad_token / intents / offline"""

    def __init__(self, store, get_cfg, broadcast, key: bytes, log) -> None:
        self.store, self.get_cfg, self.broadcast, self.key, self.log = store, get_cfg, broadcast, key, log
        self.state, self.error, self.me = "no_token", None, None
        self.client: discord.Client | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.members: dict[str, tuple[str, str]] = {}    # username -> (id, display name)
        self._wake: asyncio.Event | None = None
        self._poster_task = None
        self.last_seen: float | None = None

    # ---------------- lifecycle ----------------
    def start(self, token: str | None) -> None:
        self.stop()
        if not token:
            self._set("no_token")
            return
        self._set("connecting")
        self.thread = threading.Thread(target=self._thread, args=(token,), name="discord", daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 10) -> None:
        """Disconnect from Discord, waiting at most `timeout` seconds for each step."""
        if self.client and self.loop and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.client.close(), self.loop).result(timeout)
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout)
        self.client = self.thread = self._poster_task = self._wake = None
        if self.state not in ("bad_token", "intents"):
            self._set("offline" if self.state != "no_token" else "no_token")

    def _set(self, state: str, error: str | None = None) -> None:
        self.state, self.error = state, error
        self.broadcast("state")

    def _thread(self, token: str) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self.client = client = discord.Client(intents=intents, chunk_guilds_at_startup=True)
        self._wire(client)
        try:
            self.loop.run_until_complete(client.start(token))
        except discord.LoginFailure:
            self._set("bad_token", "Discord didn't accept this token. Copy it again from the Developer Portal "
                                   "(Bot → Reset Token).")
        except discord.PrivilegedIntentsRequired:
            self._set("intents", "Turn on Message Content Intent and Server Members Intent for your bot in the "
                                 "Developer Portal (Bot page), then press Reconnect.")
        except Exception as e:   # network etc.
            self.log(f"bot stopped: {type(e).__name__}: {e}")
            self._set("offline", f"{type(e).__name__}: {e}")
        finally:
            try:
                if not client.is_closed():
                    self.loop.run_until_complete(client.close())
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            self.loop.close()
            self.loop = None

    def run(self, coro, timeout: float = 30):
        """Run a coroutine on the bot's loop from another thread."""
        if not (self.loop and self.client and self.state == "online"):
            coro.close()
            raise RuntimeError("The bot isn't online.")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ---------------- events ----------------
    def _wire(self, client: discord.Client) -> None:
        @client.event
        async def on_ready() -> None:
            self.me = {"name": client.user.name, "id": str(client.user.id),
                       "avatar": client.user.display_avatar.url}
            self._load_members()
            self._set("online")
            if self._poster_task is None or self._poster_task.done():
                self._wake = asyncio.Event()
                self._poster_task = asyncio.create_task(self._poster())
            self.log(f"online as {client.user.name}")
            await self._catch_up()
            self.kick()
            changed = self.store.rematch(self.match)
            for c in changed:
                await self._repost(c)
            if changed:
                self.broadcast("data")
            await self._send_pending()

        @client.event
        async def on_message(m: discord.Message) -> None:
            if str(m.channel.id) in self._sources():
                await self._handle(m)

        @client.event
        async def on_member_join(member: discord.Member) -> None:
            self._load_members()
            changed = self.store.rematch(self.match)
            for c in changed:
                await self._repost(c)
            if changed:
                self.broadcast("data")

        @client.event
        async def on_member_update(before, after) -> None:
            if before.name != after.name:
                self._load_members()

        @client.event
        async def on_guild_join(guild) -> None:
            self._load_members()
            self.broadcast("state")

        @client.event
        async def on_guild_remove(guild) -> None:
            self._load_members()
            self.broadcast("state")

    def _sources(self) -> set[str]:
        return set(self.get_cfg().get("sources", []))

    def _load_members(self) -> None:
        mem: dict[str, tuple[str, str]] = {}
        for m in self.client.get_all_members():
            if not m.bot:
                mem[m.name.lower()] = (str(m.id), m.name)
        self.members = mem

    def match(self, tag: str | None):
        return self.members.get(tag) if tag else None

    async def _catch_up(self) -> None:
        """Messages posted while the app was closed. A channel added just now starts from now (older checkouts are
        never pulled in, like aco-tool)."""
        for cid in sorted(self._sources()):
            ch = self.client.get_channel(int(cid))
            if ch is None:
                continue
            last = self.store.meta(f"last:{cid}")
            if last is None:
                self.store.set_meta(f"last:{cid}", str(discord.utils.time_snowflake(datetime.now().astimezone())))
                continue
            try:
                async for m in ch.history(after=discord.Object(int(last)), limit=None, oldest_first=True):
                    await self._handle(m)
            except discord.Forbidden:
                self.log(f"can't read history of channel {cid}")

    async def _handle(self, m: discord.Message) -> None:
        cid = str(m.channel.id)
        last = self.store.meta(f"last:{cid}")
        if last is None or int(last) < m.id:
            self.store.set_meta(f"last:{cid}", str(m.id))
        if not m.embeds:
            return
        rec = message_record(m)
        try:
            p = parse.parse(rec, self.key)
        except Exception as e:   # one odd webhook must never stop the bot
            self.log(f"couldn't read message {m.id}: {type(e).__name__}")
            return
        if not p:
            return
        if p["kind"] == "unknown_sender":
            self.store.skip(p["sender"], rec["ts"])
            return
        if p["kind"] == "cancel":
            c = self.store.cancel_by_order(p["order_fp"], parse.BOTS.get(p["bot"], "bot"))
            if c:
                await self._repost(c)
                self.broadcast("data")
            return
        if p["kind"] != "success":
            return
        c = self.store.add_checkout(rec, p, self.match, post=bool(self.get_cfg().get("output")))
        if not c:
            return
        self.last_seen = time.time()
        self.kick()
        self.broadcast("checkout")

    # ---------------- posting ----------------
    def _output(self):
        oid = self.get_cfg().get("output")
        return self.client.get_channel(int(oid)) if oid else None

    def kick(self) -> None:
        """Wake the poster (safe from any thread)."""
        if self.loop and self._wake:
            self.loop.call_soon_threadsafe(self._wake.set)

    async def _poster(self) -> None:
        """Sends the saved queue of tagged posts, oldest first. One at a time normally; when 3 or more are waiting,
        up to 10 go in one message so a 2,000-checkout drop keeps up. Survives restarts (the queue is in the
        database) and retries after Discord errors."""
        while not self.client.is_closed():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            while self.state == "online":
                waiting = self.store.waiting_posts(GROUP)
                ch = self._output()
                if not waiting or ch is None:
                    break
                rows = waiting if self.store.post_backlog() >= 3 else waiting[:1]
                content, embeds = post_batch_parts(rows)
                try:
                    msg = await ch.send(content, embeds=embeds, allowed_mentions=discord.AllowedMentions(
                        users=True, roles=False, everyone=False))
                    self.store.set_posted([c["id"] for c in rows], str(msg.id), str(ch.id))
                    self.broadcast("data")
                except discord.Forbidden:
                    self.log("can't post in the output channel (missing permission); posts wait in the queue")
                    break
                except discord.HTTPException as e:
                    if 400 <= e.status < 500 and e.status != 429:   # this post itself is refused: skip, don't block
                        self.log(f"post refused ({e.status}); skipped checkout {rows[0]['id']}")
                        for c in rows:
                            self.store.drop_post(c["id"])
                    else:
                        await asyncio.sleep(5)

    async def _repost(self, c: dict) -> None:
        """Update a tagged post after it was assigned or cancelled (an edit doesn't ping again). A grouped post is
        rebuilt with all its checkouts."""
        c = self.store.checkout(c["id"]) or c
        if not c.get("posted_id"):
            return
        ch = self.client.get_channel(int(c["posted_channel"]))
        if ch is None:
            return
        content, embeds = post_batch_parts(self.store.posted_group(c["posted_id"]) or [c])
        try:
            await ch.get_partial_message(int(c["posted_id"])).edit(content=content, embeds=embeds)
        except discord.HTTPException:
            pass

    def repost(self, rows: list[dict]) -> None:
        if self.state == "online":
            for c in rows:
                asyncio.run_coroutine_threadsafe(self._repost(c), self.loop)

    async def _dm(self, user_id: str, msg: dict) -> None:
        user = self.client.get_user(int(user_id)) or await self.client.fetch_user(int(user_id))
        content, embed = to_embed(msg)
        await user.send(content, embed=embed, allowed_mentions=discord.AllowedMentions.none())

    async def _send_pending(self, key: str | None = None) -> None:
        for m in self.store.pending_messages(key):
            try:
                await self._dm(m["user_id"], messages.fee_message(self.store.message_data(m), self.get_cfg()))
                self.store.message_result(m["bill"], m["user_id"], True)
            except discord.Forbidden:
                self.store.message_result(m["bill"], m["user_id"], False,
                                          "Their DMs are closed to this bot (or they share no server with it).")
            except discord.HTTPException as e:
                self.store.message_result(m["bill"], m["user_id"], False, f"Discord error {e.status}")
            self.broadcast("data")
            await asyncio.sleep(1.2)   # stay well under Discord's DM rate limits

    def send_pending(self, key: str) -> None:
        if self.state == "online":
            asyncio.run_coroutine_threadsafe(self._send_pending(key), self.loop)

    def send_reminder(self, user_id: str, msg: dict) -> None:
        """Sent right away; raises with a plain reason if Discord refuses."""
        try:
            self.run(self._dm(user_id, msg))
        except discord.Forbidden:
            raise RuntimeError("Their DMs are closed to this bot (or they share no server with it).")
        except discord.HTTPException as e:
            raise RuntimeError(f"Discord error {e.status}")

    async def _test_post(self) -> str:
        ch = self._output()
        if ch is None:
            raise RuntimeError("Pick an output channel first.")
        _, e = post_parts({"cancelled": 0, "user_id": "x", "problem": None, "product_name": "Sample product",
                           "store": "Target", "qty": 1, "image": None,
                           "profile": f"{self.me['name'] if self.me else 'username'} 1"})
        await ch.send("Test post from ACO Forward: this is how tagged checkouts look", embed=e, allowed_mentions=discord.AllowedMentions.none())
        return f"Posted in #{ch.name}"

    def test_post(self) -> str:
        return self.run(self._test_post())

    # ---------------- setup / health ----------------
    def servers(self) -> list[dict]:
        """Every server the bot is in, with its text channels and what the bot may do there."""
        if not (self.client and self.state == "online"):
            return []
        out = []
        for g in sorted(self.client.guilds, key=lambda g: g.name.lower()):
            chans = []
            for ch in sorted(g.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position)):
                p = ch.permissions_for(g.me)
                chans.append({"id": str(ch.id), "name": ch.name, "category": ch.category.name if ch.category else "",
                              "read": p.view_channel and p.read_message_history,
                              "post": p.view_channel and p.send_messages and p.embed_links})
            out.append({"id": str(g.id), "name": g.name, "icon": g.icon.url if g.icon else None,
                        "members": g.member_count, "channels": chans})
        return out

    def channel_health(self) -> list[dict]:
        cfg = self.get_cfg()
        out = []
        want = [(c, "source") for c in cfg.get("sources", [])] + ([(cfg["output"], "output")] if cfg.get("output") else [])
        for cid, role in want:
            item = {"id": cid, "role": role, "name": cfg.get("names", {}).get(cid, cid), "ok": None, "problem": None}
            if self.state == "online":
                ch = self.client.get_channel(int(cid))
                if ch is None:
                    item.update(ok=False, problem="The bot can't see this channel (removed from the server, or the "
                                                  "channel was deleted).")
                else:
                    p = ch.permissions_for(ch.guild.me)
                    need = ([("view_channel", "View Channel"), ("read_message_history", "Read Message History")]
                            if role == "source" else
                            [("view_channel", "View Channel"), ("send_messages", "Send Messages"),
                             ("embed_links", "Embed Links")])
                    missing = [label for attr, label in need if not getattr(p, attr)]
                    item.update(ok=not missing, name=f"{ch.guild.name} › #{ch.name}",
                                problem=("Missing permission: " + ", ".join(missing)) if missing else None)
            out.append(item)
        return out

    def member_search(self, text: str, limit: int = 12) -> list[dict]:
        t = (text or "").strip().lower().lstrip("@")
        hits = [(u, i, n) for u, (i, n) in self.members.items() if not t or t in u]
        hits.sort(key=lambda h: (not h[0].startswith(t), h[0]))
        return [{"user_id": i, "user_name": n} for _, i, n in hits[:limit]]
