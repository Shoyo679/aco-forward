# Changelog

Newest first. The version is in `version.py`.

## 1.0.2 (Nov 16 2026)

- **Quit is instant:** the window and tray icon disappear right away; Discord then gets at most 3 seconds to
  disconnect (before, closing could hang up to 20 seconds while waiting for Discord). Nothing is lost: data is saved
  as it arrives, and tagged posts or DMs still waiting go out at the next start. The log says how long it took.

Verification: 25 tests; with a Discord that never answers, the window is gone in 0.03 s and the app closes in ~4 s.

## 1.0.1 (Nov 16 2026)

- **Tagged post:** one line each: **Product**, **Site** (new), **Qty**, **Profile**. The profile is a spoiler
  (click to reveal), also on the "Unassigned" line. Applies to new posts and edits; older posts keep their look.
- **Install.bat installs Python by itself** when it's missing: downloads the official Python 3.13.9 installer from
  python.org, checks its exact fingerprint and the Python Software Foundation signature, and installs it quietly for
  this Windows account (no admin). If the check fails, nothing is installed.
- **Guide:** download without a GitHub account (the repository is public); no separate Python step.

Verification: 25 tests; download check accepts the real installer and refuses a wrong fingerprint; full Install.bat
run on a fresh copy.

## 1.0.0 (Nov 16 2026)

First version.

- **Tagging:** reads Valor, Shikari, sniped.gg and Refract checkouts from your source channels and tags the
  customer (profile name before the first space = their Discord username) in your output channel. The tagged post
  shows only the tag, product, quantity and profile name. Tagged posts go through a saved queue; when many arrive at
  once, up to 10 share one message.
- **Needs assigning:** checkouts that match no one, assign by hand, remember a profile name.
- **Order status:** Active / Cancelled, by you or by the checkout bot's cancel message; sent bills are worked out
  again and **Send update** tells the customer.
- **Drops:** split after 90 quiet minutes; combine open drops that are next to each other.
- **Fees:** fee per product per drop, preview of every DM, send with progress, retry, copy text. Fee message: "You
  owe $X", lines per product, due date, How to pay note.
- **Fees tab:** owed / paid / credit, Mark paid, Remind, history.
- **Checkouts tab:** 100 per page, order numbers (shown to you only), + Add checkout for webhooks that never arrived.
- **Sharing:** Install.bat, data in %LOCALAPPDATA%\ACO Forward (safe across updates), a database copy before each
  new version, update banner, GUIDE.md and an in-app Help page, first-time tour.

Verification: 20+ automatic tests; demo with 300 customers and a 2,000-checkout drop.
