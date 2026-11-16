# ACO Forward guide

ACO Forward reads the checkout webhooks from your checkout bots (Valor, Shikari, sniped.gg, Refract), tags the
customer who owns each checkout in a Discord channel, and after each drop sends every customer their checkout
summary and fees by DM. You keep track of who owes what, and who paid, on your own PC.

This guide is also inside the app: click **Help** in the sidebar.

**Contents**

1. [Install](#1-install)
2. [Make your Discord bot](#2-make-your-discord-bot)
3. [Connect the bot in Setup](#3-connect-the-bot-in-setup)
4. [Tell your customers how to name profiles](#4-tell-your-customers-how-to-name-profiles)
5. [The tabs](#5-the-tabs)
6. [A normal drop, step by step](#6-a-normal-drop-step-by-step)
7. [Payments and reminders](#7-payments-and-reminders)
8. [Cancelled orders and missing checkouts](#8-cancelled-orders-and-missing-checkouts)
9. [Updating to a new version](#9-updating-to-a-new-version)
10. [Your data and backups](#10-your-data-and-backups)
11. [Troubleshooting](#11-troubleshooting)
12. [Privacy](#12-privacy)

---

## 1. Install

You need a Windows 10 or 11 PC. ACO Forward only works while it's running (it sits in the tray), so use the PC
that's on during drops.

1. **Download ACO Forward**: open https://github.com/Shoyo679/aco-forward/releases and, under the newest version,
   download **ACO-Forward-x.y.z.zip** (no GitHub account needed).
2. **Unzip** it somewhere permanent, for example `C:\ACO Forward` (not in Downloads, which gets cleaned up).
3. Double-click **Install.bat** in that folder. It sets up everything and makes an **ACO Forward** shortcut on
   your Desktop and in the Start menu. The first time takes 2-3 minutes.
   - **No Python yet?** Install.bat downloads Python 3.13 from python.org by itself, checks it's the genuine
     installer (signed by the Python Software Foundation), and installs it quietly for your Windows account. No
     admin password, nothing to click.
4. Open **ACO Forward**. A short tour shows you every tab; then go to **Setup**.

If Windows asks "Windows protected your PC" for Install.bat, click **More info** → **Run anyway**.

---

## 2. Make your Discord bot

ACO Forward uses **your own** Discord bot: it reads the checkout channels, posts the tags and sends the DMs under
the name and picture you give it. It takes about 5 minutes and is free.

### 2.1 Create the application

1. Open https://discord.com/developers/applications and sign in with your Discord account.
2. Click **New Application** (top right).
3. Type a name, for example "Nova ACO". Customers see this name on every tag and DM.
4. Tick the box to agree to the terms and click **Create**.
5. Optional: on **General Information**, upload an **App Icon** (the bot's picture) and click **Save Changes**.

### 2.2 Turn on the two permissions it needs (intents)

1. In the left menu click **Bot**.
2. Scroll to **Privileged Gateway Intents** and turn on:
   - **Server Members Intent**: lets the bot find a customer by their username.
   - **Message Content Intent**: lets the bot read the checkout messages.
   - (Presence Intent is not needed; leave it off.)
3. Under **Authorization Flow**, turn **Public Bot off**, so only you can add your bot to servers.
4. Click **Save Changes** at the bottom.

If you skip step 2, the app shows **Needs permissions** in red and the bot can't connect.

### 2.3 Copy the token

1. Still on the **Bot** page, click **Reset Token**, then **Yes, do it!** (you may be asked for your password or
   2FA code).
2. Click **Copy**.
3. Paste it in ACO Forward → **Setup** → step 1 → **Save and connect** (see section 3).

The token is the bot's password. Never paste it in Discord or send it to anyone. If it ever leaks, come back here,
click **Reset Token**, and paste the new one in Setup: the old one stops working at once.

### 2.4 Add the bot to your servers

1. In the left menu click **OAuth2**, then find **OAuth2 URL Generator**.
2. Under **Scopes**, tick **bot**.
3. Under **Bot Permissions** (appears below), tick exactly these four:
   - **View Channels**
   - **Read Message History**
   - **Send Messages**
   - **Embed Links**
4. **Integration Type**: leave it on **Guild Install**.
5. Copy the **Generated URL** at the bottom and open it in your browser.
6. Pick a server and click **Authorize**. You need the **Manage Server** permission in that server.
7. **Repeat steps 5 and 6 for every server you use**:
   - the server(s) where Valor, Shikari, sniped.gg and Refract post checkouts (the "source" channels), and
   - the server where the tags should go (the "output" channel).

   They can be different servers. The bot just has to be in all of them.

### 2.5 Private channels

If a checkout channel or the output channel is private, the bot can't see it until you let it in:

1. Right-click the channel → **Edit Channel** → **Permissions** → **Add members or roles**.
2. Pick your bot (or its role) and allow **View Channel**, **Read Message History**, and for the output channel
   also **Send Messages** and **Embed Links**.

In ACO Forward → Setup, a channel the bot can't use shows **No access** or **Can't post** instead of a tick box.

### 2.6 Customers and DMs

Customers get their summary as a DM from your bot. For that to work they need to:

- share at least one server with your bot (any of the servers above), and
- allow DMs from server members (Discord: **User Settings → Content & Social → Direct Messages from server
  members**, or per server: right-click the server → **Privacy Settings**).

If a DM can't be delivered, the app tells you and gives you a **Copy text** button so you can send it yourself.

---

## 3. Connect the bot in Setup

Open ACO Forward → **Setup**.

1. **Your Discord bot**: paste the token and click **Save and connect**. After a few seconds it says
   **Signed in as <your bot>** and how many members it can see.
2. **Channels**: every server the bot is in is listed with its channels.
   - Tick **Read** on each channel where a checkout bot posts its checkouts.
   - Pick one **Output** channel for the tagged posts.
   - Click **Save channels**, then **Send test post**: a test card should appear in your output channel.
   - Don't let aco-tool (or any other mirror) post into the same output channel, or every checkout shows twice.
   - The bot starts reading from the moment a channel is added; older checkouts aren't pulled in.
3. **Profile name guideline**: **Copy for customers** and send it to them (see section 4).
4. **Fee messages**: write your **How to pay** note (for example "Cash App $you or PayPal you@example.com") and
   when payment is due (days after the summary; 0 = no due date). Click **Save**.
5. **App**: turn on **Start with Windows** so ACO Forward is always running in the tray.

The **Getting started** checklist on Home ticks itself off as you go.

---

## 4. Tell your customers how to name profiles

The tag comes from the profile name: **everything before the first space is the customer's Discord username**.

- Name every profile `<your Discord username> <anything>`.
- Use the **username** (the lowercase name under your display name when you click your avatar), not the
  display name or a server nickname.
- Good: `nova.runs 1`, `nova.runs 2`, `nova.runs 1cxd`, `nova.runs amex`
- Not tagged: `nova.runs1` (no space), `Nova 1` (display name). These land in **Needs assigning** and you can
  give them to the right person by hand.

Capital letters don't matter.

---

## 5. The tabs

### Home
Your control room. The bot's status (online, connecting, needs attention), today's checkouts, how many were tagged,
how many need assigning, and how much is owed to you. **Live checkouts** shows the newest ones as they arrive.
**Bot health** lists each channel (green = fine, red = a problem with the exact reason), tags still waiting to be
posted, senders that were skipped, failed DMs and bills that changed since they were sent.

### Checkouts
Every checkout, 100 per page. Filter by drop, customer and order status, or search a product, profile, customer or
**order number** (order numbers are only shown here, never in Discord).
- **Order status**: click **Active** / **Cancelled** to switch it. Cancelled orders aren't charged.
- **+ Add checkout**: for a checkout the checkout bot never posted (see section 8).
- The **Tag** column says how each checkout found its owner: from the profile name, a remembered name, or by you.

### Needs assigning
Checkouts whose profile name doesn't start with a username the bot can find. They're grouped by profile name with
the reason. Tick them, search the customer, click **Assign**. Tick **Always use this customer for …** to remember
that profile name, so it's tagged automatically next time. A drop can't be sent while any of its checkouts are here.

### Drops
A drop starts with the first checkout and ends after **90 minutes without a checkout**.
- Each card shows the time, checkouts, items, customers, and its state: **Needs assigning**, **Ready for fees** or
  **Sent**.
- **Combine**: tick two or more open drops that are next to each other (for example a restock after a long pause)
  and click **Combine selected**. A sent drop in between is skipped and stays separate. **Undo combine** splits
  them again.
- Click a drop to open it:
  1. **Fees per product**: type a fee per item for each product (**Use last fees** fills in what you charged last
     time).
  2. **Preview**: the customer list (search, sort, filter) and, on the right, exactly the message the selected
     customer will get.
  3. **Send summaries**: confirms the list and the total, then sends every DM in the background with a progress
     bar. The drop is then locked so nobody can be billed twice.
- On a sent drop: **Retry failed DMs**, **Copy text** for anyone who couldn't get it, and **Send update** for a
  customer whose bill changed after you cancelled or re-activated one of their orders.

### Fees
Every customer's balance: owed, billed, paid, drops, last activity, **Overdue** when the due date has passed, and
**Credit** if they paid more than they now owe.
- **Mark paid**: the full amount or what they actually paid, with a note (PayPal, cash...).
- **Remind**: previews and sends a payment reminder DM listing what's still open per drop (payments pay off the
  oldest drop first). The row shows when you last reminded them.
- **History**: every bill, change and payment for that customer; a payment can be undone there.

### Setup
Bot token, channels, the profile name guideline, fee message settings, Start with Windows, the data folder, the
version and **Check for updates**, and **Replay tour**.

### Help
This guide.

---

## 6. A normal drop, step by step

1. Before the drop: Home shows **Online and tagging**.
2. During the drop: each checkout is tagged in your output channel (when many arrive at once, up to 10 share one
   message). Watch **Needs assigning** for badly named profiles and assign them.
3. After the drop (90 quiet minutes, or combine if it came in waves): open **Drops** → the drop.
4. Missing any checkouts? Add them now (**+ Add checkout**).
5. Type the fees, check a few previews, click **Send**.
6. Watch the progress bar; fix anyone listed under **Not delivered** (Retry, or Copy text and send it yourself).
7. Later: **Fees** → **Mark paid** as payments come in, **Remind** anyone who's late.

---

## 7. Payments and reminders

- The fee message says **You owe $X**, one line per product (`qty × fee = subtotal`), the due date and your
  **How to pay** note.
- Record each payment with **Mark paid**. Part payments are fine; the rest stays owed.
- **Remind** sends one customer what's still open, drop by drop, marked **overdue** after the due date.

---

## 8. Cancelled orders and missing checkouts

**Cancelled orders**: when a checkout bot posts a cancel message for an order (same order number), ACO Forward marks
the checkout **Cancelled** by itself. You can also switch any checkout on the Checkouts tab. If its drop was already
sent, the customer's bill is worked out again with the fees you used, their balance changes by the difference, and
the drop page shows **Changed since sent** with a **Send update** button.

**Missing checkouts**: sometimes Discord drops or rate-limits a checkout bot's webhook, so the checkout never
reaches the channel and ACO Forward can't see it. If a customer tells you about one, use **+ Add checkout**
(Checkouts tab or the drop page): customer, product, quantity, order number and time. Adding is refused when that
order number is already saved, so nobody is billed twice. Add them **before** sending the drop; once a drop is
sent, a late one goes into a new drop.

---

## 9. Updating to a new version

When a new version is out, a banner at the top of ACO Forward says what's new, with a **Download** button. Nothing
installs by itself:

1. Click **Download** (or open the GitHub **Releases** page) and download the new **ACO-Forward-x.y.z.zip**.
2. Quit ACO Forward: right-click the monkey in the tray → **Quit ACO Forward**.
3. Unzip the new version **over the old folder** (choose "Replace the files"), or into a new folder.
4. Double-click **Install.bat** again. It only installs what changed and refreshes the shortcuts.
5. Open ACO Forward. Setup shows the new version number.

Your data, settings and token are **not** in the program folder, so updating never touches them. The first time a
new version opens your data, it keeps a copy of the old database first (see section 10).

---

## 10. Your data and backups

Everything is stored on your PC in **`%LOCALAPPDATA%\ACO Forward`** (paste that in the File Explorer address bar,
or Setup → **Open folder**):

- `forward.db`: checkouts, drops, fees, messages, payments
- `config.json`: channels and settings; the bot token is encrypted for your Windows account
- `order.key`, `aco-forward.log`
- `backups\forward-before-x.y.z.db`: a copy made before each update (the newest 10 are kept)

**To back up**: quit ACO Forward and copy the whole folder somewhere safe.
**To restore**: quit ACO Forward and copy the folder back (or copy a `backups\forward-before-….db` over
`forward.db`). The token only works on the same Windows account; on a new PC, paste it again in Setup.

---

## 11. Troubleshooting

| What you see | What to do |
|---|---|
| **Not set up** | Paste your bot token in Setup (section 3). |
| **Token not accepted** | Copy it again: Developer Portal → Bot → Reset Token (section 2.3). |
| **Needs permissions** | Turn on Server Members Intent and Message Content Intent (section 2.2), then **Reconnect**. |
| **Offline** | Check your internet, then **Reconnect** (Home or the tray menu). |
| A channel shows **No access** / **Can't post** | Let the bot into that private channel (section 2.5), then **Refresh**. |
| Checkouts don't show up | Is that channel ticked **Read** in Setup? Is the checkout bot one of Valor, Shikari, sniped.gg, Refract? Other senders are listed under "Skipped senders" on Home. |
| Checkouts aren't tagged | The profile name doesn't start with a username, or that person isn't in any server with your bot. Assign them in **Needs assigning**. |
| **Not delivered** on a DM | They block DMs from your bot or share no server with it. **Retry** after they fix it, or **Copy text** and send it yourself. |
| **Posting tags: N waiting** | Discord only allows about 5 messages per 5 seconds in a channel; the queue catches up by itself. |
| Install.bat says ACO Forward is running | Quit it from the tray, then run Install.bat again. |

The log file `aco-forward.log` (in the data folder) helps if you need to ask for support.

---

## 12. Privacy

- Nothing leaves your PC except what your bot posts in Discord and the DMs you send. The dashboard only opens on
  this PC (127.0.0.1).
- Emails, account logins, proxies, addresses and card details from the webhooks are never saved.
- Order numbers are saved for your Checkouts tab only; they never appear in tags or DMs.
- The tagged post shows only the tag, product, site, quantity and profile name (the profile is hidden until
  someone clicks it).
- The update check downloads one small public file with the latest version number; it sends nothing about you.
