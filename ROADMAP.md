# CalibrationDB — Roadmap

## What exists today (v0.3, June 2026)

| Command                    | Purpose                                                                     |
|----------------------------|-----------------------------------------------------------------------------|
| `sync`                     | CSV -> DB or DB -> CSV (auto-detected); interactive confirm                 |
| `diff`                     | Compare CSV vs DB, two CSVs, two tags/dates, or a tag vs current state      |
| `status`                   | Sync state + git status for both files; scriptable exit code                |
| `review`                   | Interactive per-change confirmation with comments                           |
| `show`                     | Current value + metadata by name/glob or by description/datatype/unit/source filter; `--at TAG`; table view by default |
| `log`                      | History, all params or one (`git log`-style optional NAME, glob supported); `--since`; table view by default; `--by-tag`; interleaved tag markers |
| `tag` / `tags`             | Named snapshot labels; `--at DATETIME` for back-dating                      |
| `annotate`                 | Retroactively set/fix sync comments on history entries                      |
| `restore`                  | Revert params to a tag or to the value before last change                   |
| `validate`                 | Check values against Min/Max/DataType constraints                           |
| `add/update/rename/delete` | Manual CRUD via CLI                                                         |
| `load`                     | Bulk import CSV or JSON (no history)                                        |
| `export`                   | Dump active params to CSV                                                   |
| `install-hook`             | Git pre-commit hook: auto-sync staged CSVs                                  |

Core internals: two CSV formats auto-detected, SHA-256 sync guard, soft delete,
`_caldb_meta` for sync state, `_caldb_tags` for snapshots, metadata-only change
tracking (`ChangeType='meta'`), type-inherent range validation.

---

## Next up

### A. Python test suite

Unit and integration tests using `pytest` + `click.testing.CliRunner`. A `tests/` directory now
exists (`pip install -e ".[test]"`, then `pytest`) with regression coverage for calibration
vectors longer than 10 values (`tests/test_multicol_values.py`, commit 92de356). Everything else
below is still open.

Priority areas:

- `cal_db_util.py`: `_canonicalise_value`, `compute_diff`, `compute_db_to_csv_diff`,
  `get_parameters_at_tag`, `compute_restore_diff`, tag/restore round-trips
- CLI integration: sync direction detection, status exit codes, diff output,
  restore --at tag, search filters
- Edge cases: multicol vs singlecol CSV, never-synced state, conflict detection,
  meta-only sync, annotate time-window matching

---

## Backlog

### `diff --export` — write diff results to CSV files, for later use as an update source

`caldb diff` gains an `--export`/`-o DIR` option that writes the diff to disk
as CSV, so the result of a comparison can be handed off and re-applied later
(e.g. via `caldb load`, a future `caldb merge`, or manual copy/paste into the
main CSV) instead of only being printed to the terminal. Works for all three
comparison modes already shipped (CSV-vs-DB default, `-f a -f b` CSV-vs-CSV,
`--from/--to` tag/date/sync-comment):

```bash
caldb diff -f baseline.csv -f current.csv --export out/
caldb diff --from v1.0 --to v1.2 --export out/
caldb diff --export out/           # default CSV-vs-DB mode
```

File naming is `<prefix>_<suffix>.csv`, prefix = new-side label (second `-f`
file's stem, `--to` ref, or `CSV` for the default mode):

```
out/<prefix>_upd1.csv   changed rows, OLD-side values   (Name + Value_1..10)
out/<prefix>_upd2.csv   changed rows, NEW-side values   (Name + Value_1..10)
out/<prefix>_new.csv    rows only on the NEW side       (full row incl. metadata)
out/<prefix>_del.csv    rows only on the OLD side       (full row incl. metadata)
out/<prefix>_meta.csv   metadata-only changes: Name, Field, OldValue, NewValue
                         (one row per changed field, from meta_only's `detail`
                          string, or from get_meta_changes_between for the
                          --from/--to mode — split the ' | '-joined string on
                          write)
```

Design notes:

- Reuses `compute_diff`/`compute_snapshot_diff`'s `added`/`changed`/`deleted`/
  `meta_only` output directly — this is purely a CSV-writing step over data
  the diff machinery (built in the `diff --from/--to`, `-f -f` work) already
  produces; no new comparison logic needed.
- `_upd1`/`_upd2` intentionally use the delta shape (`Name` + `Value_1..10`
  only, no metadata columns) so they match what `caldb load` already accepts
  and what a future `caldb merge --from` would consume as a source file —
  this is the "use later as a source of update" path.
- `_new`/`_del` need full rows (including DataType/Unit/Min/Max/Description/
  Source) since re-adding a deleted parameter or importing a new one needs
  the metadata, not just a value.
- Respects whichever CSV format (multicol vs singlecol) the *new*-side file
  used, if the new side is a CSV; defaults to multicol when the new side is
  DB-only (tag/date mode) since that's this repo's primary format.
- Ported from `compare_cal_files` in the external `cal_merge.py` script
  (same four-file split for CSV-vs-CSV), extended here to also cover the
  DB-backed modes and to add the `_meta.csv` file, which `cal_merge.py`
  doesn't have (it has no metadata-only change tracking).

### `uninstall-hook`

Remove the caldb block from `.git/hooks/pre-commit` (inverse of `install-hook`).

### `stats` command

```
Parameters:   313 active, 4 deleted
Changes:      1 027 total (148 this month)
Most changed: TempCtlSetPnt (12), FanSpdMapX (9), PmpSpdMin (7)
Last sync:    2026-06-08 14:10  (in sync)
```

### Export preserving original CSV format

`--format multicol` / `--format singlecol` on `export` so output matches
the original column layout and opens correctly in Excel.

### Shell completions

Click has built-in completion generation:
```bash
caldb --install-completion   # bash / zsh / fish
```

### `merge` -- apply changes from another DB or CSV (including a `diff --export`)

```bash
caldb merge --from other.db                    # preview what differs
caldb merge --from other.csv                   # source can be a bare CSV too, not just a .db
caldb merge --from out/current_upd2.csv         # or a diff --export delta file, applied back
caldb merge --from other.db --apply             # apply non-conflicting, prompt on conflicts
caldb merge --from other.db --apply --all       # accept-all, no per-row prompt (scripting)
```

The write-back counterpart to `diff`/`diff --export`: `diff` (and its export
files) only show what differs; `merge` is what actually applies a subset of
those changes into the tracked DB, going through normal history so it's
indistinguishable from a hand-made `update`/`add`/`delete`.

Design notes:

- Preview step reuses `compute_diff` (source is a `.db`, via `_get_all_active`)
  or `compute_snapshot_diff` (source is a bare CSV, via `_load_csv_params`) --
  same machinery `diff` already uses, so the preview output should look like
  `diff`'s table/plain view, not a separate format.
- `--from` accepts: another `.db` file, a full calibration CSV, *or* a delta
  CSV as produced by `diff --export` (`_upd2.csv` shape: `Name` + `Value_1..10`
  only) -- detect the delta shape the same way `cal_merge.py`'s
  `apply_cal_updates` does (fewer columns present, no metadata columns) and
  treat it as value-only updates against existing parameters (no add/delete
  from a delta file, since it has no metadata to create a new parameter with).
- Interactive per-row confirmation is y/n/a(all), modeled on
  `apply_cal_updates` in the external `cal_merge.py` script -- but writes
  through `CalibrationDatabase.update_parameter`/`add_parameter`/
  `soft_delete` (so applied changes go through normal history tracking,
  `sync_comment`, etc.) rather than editing the destination CSV directly.
- Conflicts: a row is "conflicting" if the destination's current value
  differs from what the *preview* saw (i.e. someone else changed it between
  `merge`'s preview and apply step, or `--from` is stale) -- re-diff
  immediately before applying each row and skip with a warning if it no
  longer matches, rather than silently overwriting.
- Metadata-only changes from the source (`meta_only` / a `diff --export`
  `_meta.csv`) should also be mergeable, applied via the same path
  `apply_changes` already uses for CSV-sourced meta updates
  (`_format_meta_diff` + a `'meta'` history row) -- don't special-case them
  out of `merge` just because they're not a plain value change.
- `--apply` without `--all` prompts per row (matches `cal_merge.py`); without
  `--apply` at all, `merge` is preview-only (same default-safe behavior as
  `diff`).

### Multi-CSV tracking in one DB

Track several CSV files (e.g. per-subsystem) in a single `.db`:
```bash
caldb sync -f subsys_a.csv -f subsys_b.csv
caldb log --file subsys_a.csv
```

### HTML / Markdown change report

```bash
caldb report -f report.html
caldb report --since "sprint 4" -f delta.md
```

### Python API improvements

- Context manager: `with CalibrationDatabase('cal.db') as db:`
- `db.to_dataframe()` -- returns a pandas DataFrame of active parameters
- `fields=` filter on `get_parameters()`

### Parameter validation rules

Store per-parameter allowed-value lists in a `_caldb_rules` table.
```bash
caldb rule -n FanSpdReqMax --allowed "0,10,20,50,90,100"
```
Checked on every `sync`/`add`/`update`.
