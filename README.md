# ACO Forward

A Windows tray app with a dashboard for ACO runners. Your own Discord bot reads checkout webhooks (Valor, Shikari,
sniped.gg, Refract), tags the customer in an output channel, and after each drop sends every customer a checkout
summary with their fees by DM.

- **Tag:** the profile name up to the first space is the customer's Discord **username**
  (`nova.runs 1cxd` → `@nova.runs`). Capitals are ignored.
- **Tagged post:** the tag, then one line each: Product, Site, Qty, Profile (a spoiler: click to reveal), plus the
  product picture. No checkout bot, price, account, email, proxy or order number.
- **Needs assigning:** checkouts whose profile name matches nobody are listed with a warning. Assign them by hand,
  and optionally make the app always use that customer for that profile name.
- **Drops:** a drop ends after 90 minutes with no checkouts. Combine open drops that are next to each other (a sent
  drop between them is skipped and stays separate), and undo, before billing.
- **Order status:** each checkout is Active or Cancelled (by you, or by the checkout bot's own cancel message). Cancelled
  orders aren't charged. If the drop was already sent, that customer's bill is worked out again with the fees used
  then, their balance moves by the difference (it can become a credit), and the drop page offers **Send update**.
- **Fees:** set a fee per product per drop (last fees are offered), preview every DM, then send. Customers with no
  checkouts get nothing. A sent drop is locked and can't be billed twice. Cancelled orders (matched by a one-way code
  of the order number) aren't charged.
- **Fee message** (design B): "You owe $X" first, one line per product, the due date and your **How to pay** note
  (both set in Setup). The dashboard preview is built by the same code as the DM (`messages.py`).
- **Owed / paid:** balance per customer, record full or part payments, history with undo, **Remind** (a DM with
  what's still open per drop, oldest paid first, marked overdue after the due date).
- **Order numbers:** shown on the Checkouts tab (column + search) for you only; never posted or sent to customers.
- **Missed webhooks:** if a checkout bot's webhook never reached Discord, add the checkout by hand (Checkouts tab or
  the drop page). Refused when that order number is already saved, so nobody is billed twice.
- **Big drops:** tagged posts go through a saved queue; when posts pile up, up to 10 checkouts share one message, so
  2,000 checkouts keep up with Discord's limit (~5 messages per 5 s per channel). The Checkouts tab loads 100 at a
  time; the drop page lists customers in a searchable table (50 per page) with one message preview.
- **Bot health:** online state, channel access and missing permissions, posting queue, skipped senders, failed DMs.
- Source channels and the output channel can be in different servers; the bot has to be in both.
- **Stellar** isn't read yet: its webhook layout gets added from a real test webhook (it's counted under skipped
  senders until then).

## Install (for whoever runs it)

1. Download `ACO-Forward-x.y.z.zip` from the GitHub release and unzip it somewhere permanent.
2. Double-click **Install.bat**: installs Python 3.13 if it's missing (official python.org installer, checked by
   fingerprint and signature, per-user, no admin), makes the app's Python environment and the shortcuts.
3. Open **ACO Forward**: a short tour shows every tab; **GUIDE.md** (also the **Help** tab) explains everything,
   including how to make the Discord bot.

**Updating:** quit from the tray, unzip the new version over the folder, run Install.bat again. The app shows a
banner when a new version is out (it reads the public `latest.json` set in `version.py`; nothing installs by
itself). Releasing a version: see **RELEASING.md**; what changed: **CHANGELOG.md**.

**Data** lives in `%LOCALAPPDATA%\ACO Forward` (not the program folder), so updates never touch it; the database is
copied to `backups\` before a new version first opens it. A pre-1.0 `data\` folder is moved there automatically.

Developer options: `--demo` (made-up data in `demo-data/`, no Discord, port 8888), `--serve` (no window),
`--tray` (start hidden), `--data <folder>` (use another data folder).

## Scale (measured Nov 16 2026)

300 customers, 19 sent drops of 2,000 checkouts + a live drop of 2,000: about 60 ms per incoming checkout including
the drop list, 33 ms for the drop page, 17 ms per Checkouts page, 0.12 s to send 300 summaries, ~0.5 s to search
40,000 checkouts by order number. 40,000 checkouts take about 7 MB.

## Privacy

Everything stays on this PC in `%LOCALAPPDATA%\ACO Forward`: `forward.db` (checkouts, drops, fees), `config.json` (the
token is encrypted with Windows DPAPI for your account), `order.key` and the log. The dashboard listens on
127.0.0.1 only. Emails, proxies, addresses and card details are never saved. Order numbers are saved for your
Checkouts tab only.

## Tests

```
.venv\Scripts\python -m unittest discover -s tests
```
