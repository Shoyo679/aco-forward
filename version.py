"""ACO Forward's version. Bump it for every release (see RELEASING.md) and add a CHANGELOG.md section."""
VERSION = "1.0.0"

# Public file that says which version is newest (a public gist with only this JSON, no code):
#   {"version": "1.1.0", "date": "2026-11-20", "notes": ["What's new", "..."], "url": "<release page>"}
# The repository itself is private, so the app can't ask GitHub directly. Empty = update check off.
UPDATE_URL = "https://gist.githubusercontent.com/Shoyo679/203ad65328ad1272def4c9708f6267aa/raw/latest.json"
