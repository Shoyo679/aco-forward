# Changelog

Newest first. The version is in `version.py`.

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
