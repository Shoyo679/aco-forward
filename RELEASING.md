# Releasing a new version (for the owner)

Your friend updates by hand: they download the zip from the GitHub release, unzip it over their folder and run
Install.bat. The app tells them a new version is out by reading a small public JSON file (a gist), set in
`version.py` as `UPDATE_URL`. The repository is public (https://github.com/Shoyo679/aco-forward), so anyone can
download releases.

## Each release

1. Run the tests: `.venv\Scripts\python -m unittest discover -s tests`
2. Bump `VERSION` in `version.py` (1.0.0 → 1.0.1 for fixes, 1.1.0 for new features).
3. Add a section at the top of `CHANGELOG.md` (what changed, in plain words, plus a `Verification:` line).
4. If the database changes, add the new columns to `MIGRATIONS` in `store.py` (never rename or drop columns: the
   app adds new ones on start, and the old database is copied to `backups\` first).
5. Commit, tag and push:
   ```
   git commit -am "vX.Y.Z: <summary>"
   git tag vX.Y.Z
   git push origin main --tags
   ```
6. Make the zip (only tracked files, so no data, .venv or demo files) and the GitHub release:
   ```
   git archive --format=zip --prefix=ACO-Forward/ -o ACO-Forward-X.Y.Z.zip vX.Y.Z
   gh release create vX.Y.Z ACO-Forward-X.Y.Z.zip --title "ACO Forward X.Y.Z" --notes-file <notes.md>
   ```
7. Update the public version file (the gist behind `UPDATE_URL`) so the banner appears:
   ```json
   {"version": "X.Y.Z", "date": "YYYY-MM-DD",
    "notes": ["Short line per change", "..."],
    "url": "https://github.com/Shoyo679/aco-forward/releases/tag/vX.Y.Z"}
   ```
   `gh gist edit 203ad65328ad1272def4c9708f6267aa latest.json` (or edit it on gist.github.com).

## First-time setup (once)

- Create the repository `Shoyo679/aco-forward` and push (made public on Nov 16 2026: never commit tokens or data;
  `.gitignore` keeps data/, demo-data/ and .venv out).
- Create the public gist with `latest.json` and put its **raw** URL (without the commit id, so it always shows the
  newest content) in `UPDATE_URL`, e.g. `https://gist.githubusercontent.com/<you>/<id>/raw/latest.json`.
