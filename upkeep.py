"""Keeping a copy of ACO Forward healthy across manual updates:
- the data lives outside the program folder (%LOCALAPPDATA%\\ACO Forward), so replacing the folder loses nothing;
- the old in-folder data/ is moved there once;
- the database is copied before a new version first opens it;
- the update check reads a small public JSON file (version.UPDATE_URL) and never installs anything.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import urllib.request
from pathlib import Path

KEEP_BACKUPS = 10


def home_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "ACO Forward"


def move_old_data(old: Path, new: Path) -> bool:
    """Move data/ from inside the program folder (before 1.0.0) to the new home, once. Never overwrites a home that
    already has checkouts; an empty one (opened once with nothing in it) is replaced."""
    if not (old / "forward.db").exists() or _has_checkouts(new / "forward.db"):
        return False
    new.mkdir(parents=True, exist_ok=True)
    for f in old.iterdir():
        target = new / f.name
        if target.exists() and target.name.startswith(("forward.db", "config.json", "order.key")):
            target.unlink()
        if not target.exists():
            shutil.move(str(f), str(target))
    try:
        old.rmdir()
    except OSError:
        pass   # something was left (already existed in the new place): kept, not deleted
    return True


def _has_checkouts(db: Path) -> bool:
    if not db.exists():
        return False
    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT 1 FROM checkouts LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def backup_before_upgrade(db_path: Path, data: Path, version: str) -> Path | None:
    """Copy the database the first time a new version opens it (data/backups/forward-before-<version>.db).
    Returns the copy, or None when this version already ran here or there's nothing to keep."""
    if not db_path.exists():
        return None
    src = sqlite3.connect(str(db_path))
    try:
        try:
            row = src.execute("SELECT v FROM meta WHERE k='app_version'").fetchone()
            has_data = src.execute("SELECT 1 FROM checkouts LIMIT 1").fetchone() is not None
        except sqlite3.OperationalError:   # brand-new file without tables
            return None
        last = json.loads(row[0]) if row else None
        if last == version or not has_data:
            return None
        out = data / "backups" / f"forward-before-{version}.db"
        out.parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(str(out))
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    olds = sorted(out.parent.glob("forward-before-*.db"), key=lambda p: p.stat().st_mtime)
    for p in olds[:-KEEP_BACKUPS]:
        p.unlink()
    return out


def parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest(url: str, timeout: float = 8) -> dict | None:
    """The newest version's info, or None (no URL set, offline, or a bad file). Never raises."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ACO-Forward-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            info = json.loads(r.read(64_000).decode("utf-8"))
        if not isinstance(info, dict) or not info.get("version"):
            return None
        notes = info.get("notes") or []
        return {"version": str(info["version"])[:20], "date": str(info.get("date") or "")[:20],
                "notes": [str(n)[:300] for n in notes][:20] if isinstance(notes, list) else [str(notes)[:300]],
                "url": str(info.get("url") or "") if str(info.get("url") or "").startswith("https://") else ""}
    except Exception:
        return None
