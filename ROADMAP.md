# CalibrationDB — Roadmap

## What exists today (v0.3, June 2026)

| Command                    | Purpose                                                                     |
|----------------------------|-----------------------------------------------------------------------------|
| `sync`                     | CSV -> DB or DB -> CSV (auto-detected); interactive confirm                 |
| `diff`                     | Compare CSV vs DB, two CSVs, two tags/dates, or a tag vs current state      |
| `status`                   | Sync state + git status for both files; scriptable exit code                |
| `review`                   | Interactive per-change confirmation with comments                           |
| `show`                     | Current value + metadata; `--at TAG`; `-T` table view                       |
| `search`                   | Filter params by description, datatype, unit, source; `-T` table view       |
| `changes`                  | Recent history; `--since`; `-T` table; `--by-tag`; interleaved tag markers  |
| `log`                      | Full history for one parameter                                              |
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

Unit and integration tests using `pytest` + `click.testing.CliRunner`.
Priority areas:

- `cal_db_util.py`: `_canonicalise_value`, `compute_diff`, `compute_db_to_csv_diff`,
  `get_parameters_at_tag`, `compute_restore_diff`, tag/restore round-trips
- CLI integration: sync direction detection, status exit codes, diff output,
  restore --at tag, search filters
- Edge cases: multicol vs singlecol CSV, never-synced state, conflict detection,
  meta-only sync, annotate time-window matching

---

## Backlog

### `diff --export` — write diff results to CSV files

`caldb diff` (all comparison modes: CSV-vs-DB, CSV-vs-CSV, tag/date-vs-tag/date)
gains an `--export`/`-o` option that writes the diff to disk instead of (or in
addition to) printing it, e.g.:

```bash
caldb diff -f baseline.csv -f current.csv --export out/
#   out/current_upd1.csv   rows that changed, old (baseline) values
#   out/current_upd2.csv   same rows, new (current) values
#   out/current_new.csv    rows only in current
#   out/current_del.csv    rows only in baseline
```

Ported from `compare_cal_files` in the external `cal_merge.py` script, which
already implements this export shape for CSV-vs-CSV. Reuses
`compute_snapshot_diff`'s `added`/`changed`/`deleted` output — just needs a
CSV-writing step per diff mode.

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

### `merge` -- apply changes from another DB or CSV

```bash
caldb merge --from other.db          # preview what differs
caldb merge --from other.csv         # source can be a bare CSV too, not just a .db
caldb merge --from other.db --apply  # apply non-conflicting, prompt on conflicts
```

Interactive per-row y/n/a(all) confirmation, modeled on `apply_cal_updates` in
the external `cal_merge.py` script -- but writes through `CalibrationDatabase`
(so applied changes go through normal history tracking, `sync_comment`, etc.)
rather than editing the destination CSV directly. `--from` accepts either
another `.db` or a bare CSV (parsed with `_load_csv_params`, no DB needed on
the source side). Builds on `compute_snapshot_diff` for the preview.

### Multi-CSV tracking in one DB

Track several CSV files (e.g. per-subsystem) in a single `.db`:
```bash
caldb sync -f subsys_a.csv -f subsys_b.csv
caldb changes --file subsys_a.csv
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
