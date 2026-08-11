# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CalibrationDB (`caldb`) is a Python CLI that tracks per-parameter change history for calibration
CSV files (named-parameter tables used to tune embedded systems: thresholds, PID gains, speed
maps, etc.). The CSV remains the primary editing surface (opened in Excel/text editor, versioned
in git as a whole file); a SQLite `.db` file sits alongside it and records every individual
parameter add/update/delete/meta-change with timestamps, old/new values, and comments — the way
git tracks a file, `caldb` tracks a *parameter*.

Read `README.md` for full CLI reference and output examples; `ROADMAP.md` for planned work
(notably: no test suite exists yet — item A in the roadmap).

## Commands

```bash
pip install .                    # install (editable: pip install -e .)
caldb --help                     # after install, entry point is `caldb` (see pyproject.toml [project.scripts])
python -m calibrationdb.cal_db_cli --help   # run without installing

.\example\run_example.ps1        # scripted end-to-end walkthrough of the CLI (PowerShell)
```

There is no test suite, linter, or CI config in this repo currently. `caldb --test` (global flag)
runs any single command against a real DB connection but rolls back the transaction at the end —
useful for manually verifying a command's effect without persisting it.

## Architecture

Everything lives in `src/calibrationdb/`, split into exactly two files:

- **`cal_db_util.py`** — `CalibrationDatabase` class: all persistence and domain logic. Owns the
  sqlite3 connection, schema creation/migration (`ALTER TABLE ... ADD COLUMN` wrapped in
  try/except for old DBs), CSV parsing for both supported formats, diffing, and change history.
  Also defines the `CalibrationParameter` namedtuple (the in-memory representation of one CSV
  row) and `_validate_value` (Min/Max/DataType/Size constraint checks).
- **`cal_db_cli.py`** — the `click` CLI. One function per subcommand (`sync`, `review`, `show`,
  `search`, `diff`, `status`, `tag`, `changes`, `log`, `annotate`, `restore`, `add`/`update`/
  `rename`/`delete`, `load`, `export`, `install-hook`). Path-resolution helpers (`_resolve_db`,
  `_resolve_pair`) implement the DB/CSV auto-detection rules documented in the README; keep new
  commands consistent with that pattern rather than adding ad-hoc path handling.

`build/lib/calibrationdb/` is a stale copy of these two files left over from a previous
`python -m build` — it is gitignored and not the source of truth; always edit under `src/`.

### Data model (SQLite, one file per project)

- `calibration` — current state of every parameter (one row per name), keyed by `MID`
  (md5 of `UID = prefix + name`, e.g. `CAL-FanSpdReqMax`). Soft-deleted rows are kept with
  `Deleted=1` rather than removed, so history stays intact.
- `calibration_history` — append-only log of every add/update/delete/restore/meta change:
  old/new value, old/new comment, timestamp, and an optional `SyncComment` (the session-level
  label passed via `sync -c` / `review` / `annotate`).
- `_caldb_meta` — key/value store used for the sync guard: a SHA-256 hash + timestamp of the CSV
  at last sync (`get_sync_status`), and a `db_changed` timestamp set whenever a CLI write
  (`add`/`update`/`delete`/`rename`) touches the DB without going through a CSV sync. Comparing
  these two is what drives `caldb status`'s exit codes and `sync`'s auto-detected direction.
- `_caldb_tags` — named snapshots (`caldb tag`). `get_parameters_at_tag` reconstructs
  point-in-time state by taking, for each parameter, the latest history row at or before the
  tag's timestamp — this is also what `restore --at TAG` and `show --at TAG` build on.

### Two CSV formats, auto-detected from headers

- **Multi-column**: `Value_1..Value_10` (array elements in separate columns) — detected when
  `Value_1` is a header.
- **Single-column**: one `Value` column, arrays as `[0 80]` or `[0, 1, 2]`.

`_canonicalise_value` normalizes both bracket styles and comma/space separators to a canonical
space-separated string so value comparisons never produce false diffs across formats. Any code
that compares parameter values (diffing, sync, restore) must go through this normalization, not
raw string equality.

### Sync directions

`sync` is bidirectional: default CSV→DB (`compute_diff` / `apply_changes` / `sync_from_csv`), or
`--to-csv` for DB→CSV (`compute_db_to_csv_diff` / `write_back_to_csv`), with direction
auto-detected from which side changed (`get_sync_status` vs `get_db_changed_time`) when the flag
is omitted. `diff`/`status`/`review` reuse these same diff-computation methods rather than
duplicating comparison logic — follow that pattern for new read-only inspection commands.
