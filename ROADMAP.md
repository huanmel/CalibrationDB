# CalibrationDB — Roadmap

## What exists today (v0.3, June 2026)

| Command                    | Purpose                                                                     |
|----------------------------|-----------------------------------------------------------------------------|
| `sync`                     | CSV -> DB or DB -> CSV (auto-detected); interactive confirm                 |
| `diff`                     | Show what differs between CSV and DB (current state)                        |
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

### B. `diff` — extended comparison modes

Currently `caldb diff` only compares the current CSV vs the current DB.
Extend to support comparing any two snapshots:

```bash
# Between two tags (uses get_parameters_at_tag for each side)
caldb diff --from v1.0 --to v1.2

# Between a tag and current state
caldb diff --from v1.0

# Between two dates
caldb diff --from 2026-06-01 --to 2026-06-10

# Between two CSV files (no DB needed)
caldb diff -f baseline.csv -f current.csv
```

Implementation: `--from` / `--to` resolve to a timestamp (from tag name, ISO date,
or sync comment). `get_parameters_at_tag` already reconstructs state at any
timestamp so the tag/date cases are cheap to add. File-vs-file is independent
(load both CSVs, diff in memory).

---

## Backlog

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
caldb merge --from other.db --apply  # apply non-conflicting, prompt on conflicts
```

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
