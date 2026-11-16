"""Updates by hand: data outside the program folder, a database copy before a new version, the update check."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upkeep  # noqa: E402
from store import Store  # noqa: E402


class UpkeepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_db(self, folder: Path, version=None, rows=1) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        s = Store(folder / "forward.db")
        for i in range(rows):
            s.x("INSERT INTO checkouts(id, ts, qty) VALUES(?,?,1)", (str(i), i))
        if version:
            s.set_meta("app_version", version)
        s.db.close()

    def test_move_old_data_once(self):
        old, new = self.d / "prog" / "data", self.d / "home"
        self.make_db(old)
        (old / "config.json").write_text("{}")
        self.assertTrue(upkeep.move_old_data(old, new))
        self.assertTrue((new / "forward.db").exists() and (new / "config.json").exists())
        self.assertFalse(old.exists())
        self.make_db(old)                                  # a stray old folder later never overwrites
        self.assertFalse(upkeep.move_old_data(old, new))

    def test_move_replaces_an_empty_new_home(self):
        old, new = self.d / "prog" / "data", self.d / "home"
        self.make_db(old, rows=3)
        self.make_db(new, rows=0)                          # the new version was opened once before the move
        self.assertTrue(upkeep.move_old_data(old, new))
        s = Store(new / "forward.db")
        self.assertEqual(len(s.q("SELECT * FROM checkouts")), 3)
        s.db.close()

    def test_backup_before_upgrade(self):
        self.make_db(self.d, version="1.0.0")
        self.assertIsNone(upkeep.backup_before_upgrade(self.d / "forward.db", self.d, "1.0.0"))   # same version
        out = upkeep.backup_before_upgrade(self.d / "forward.db", self.d, "1.1.0")
        self.assertEqual(out.name, "forward-before-1.1.0.db")
        s = Store(out)
        self.assertEqual(len(s.q("SELECT * FROM checkouts")), 1)
        s.db.close()
        empty = self.d / "e"
        self.make_db(empty, rows=0)
        self.assertIsNone(upkeep.backup_before_upgrade(empty / "forward.db", empty, "1.1.0"))   # nothing to keep

    def test_versions_and_update_file(self):
        self.assertTrue(upkeep.newer("1.10.0", "1.9.3"))
        self.assertTrue(upkeep.newer("v2.0.0", "1.9.9"))
        self.assertFalse(upkeep.newer("1.0.0", "1.0.0"))
        f = self.d / "latest.json"
        f.write_text(json.dumps({"version": "1.2.0", "notes": ["New thing"], "url": "javascript:alert(1)"}))
        info = upkeep.fetch_latest(f.as_uri())
        self.assertEqual((info["version"], info["notes"], info["url"]), ("1.2.0", ["New thing"], ""))   # bad link dropped
        f.write_text("not json")
        self.assertIsNone(upkeep.fetch_latest(f.as_uri()))
        self.assertIsNone(upkeep.fetch_latest(""))


if __name__ == "__main__":
    unittest.main()
