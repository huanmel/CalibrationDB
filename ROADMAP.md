# CalibrationDB — Roadmap

## Implementation order

**Phase A — Quick wins** (done): `status`, `changes --since`, DB-changed flag
**Phase B — Safety building block**: `validate` command + wire into add/update/sync/review
**Phase C — Core workflow gap**: Bidirectional sync (DB → CSV write-back)
**Deferred**: `tag`/`restore`, `stats`, `search`, `diff`/`merge`, export format, completions

---

## What exists today (v0.1, June 2026)

| Command                    | Purpose                                           |
|----------------------------|---------------------------------------------------|
| `sync`                     | Diff CSV -> DB, record all changes                |
| `review`                   | Interactive per-change confirmation with comments |
| `show`                     | Current value + metadata; `-c` compact Name=Value |
| `changes`                  | Recent history across all params; `-c` compact    |
| `log`                      | Full history for one parameter                    |
| `add/update/rename/delete` | Manual CRUD via CLI                               |
| `load`                     | Bulk import CSV or JSON (no history)              |
| `export`                   | Dump active params to CSV                         |
| `install-hook`             | Git pre-commit hook: auto-sync staged CSVs        |

Core internals: two CSV formats auto-detected, SHA-256 sync guard, soft delete, `_caldb_meta` for metadata.

---

## Tier 1 — Quick wins (small, high value)

### 0. Bidirectional sync — DB → CSV write-back

Currently `sync` only goes CSV → DB. When parameters are edited directly via CLI
(`add`, `update`, `rename`), the CSV falls behind. This adds the reverse direction
and makes the overall sync smarter about which side is ahead.

**Pre-sync summary** — before any write, show a one-line status for each side:
```
DB   last changed: 2026-06-09 10:14  (2 CLI edits since last sync)
CSV  last changed: 2026-06-09 09:55  (matches last sync)
Direction: DB -> CSV  (auto-detected)
```

**Direction detection:**

- If only CSV changed → CSV → DB (current behaviour)
- If only DB changed (via CLI) → DB → CSV write-back
- If both changed → warn of a conflict, require `--direction csv` or `--direction db`
  to resolve, or use `review` to handle per-parameter

**DB → CSV write-back with confirmation:**

```bash
caldb sync --to-csv          # explicit reverse direction
caldb sync                   # auto-detects direction as above
```

Per-parameter prompt: `y` accept / `n` skip / `a` accept all / `q` quit.

**Git status guard** — before writing the CSV, check `git status` on that file:

- If the CSV has uncommitted changes that differ from the last sync, warn the user
  so they don't accidentally overwrite in-progress edits
- If the CSV is untracked or not in a git repo, skip silently

**Normalisation on write** — collapse double spaces, strip stray brackets, and
apply canonical value format so the CSV stays clean after write-back.

**Tracking:** a DB-changed flag (set whenever `add`/`update`/`rename`/`delete`
runs) is stored in `_caldb_meta` alongside the existing CSV hash, giving `status`
enough information to report which side is ahead.

### 1. `status` command
Single-line sync check with a scriptable exit code.
```
caldb status
# CSV is in sync with DB (last sync: 2026-06-08 14:10)
# exit 0 = in sync, exit 1 = stale, exit 2 = never synced
```
Useful in CI pipelines and shell scripts (`caldb status || caldb sync`).

### 2. `uninstall-hook`
Remove the caldb block from `.git/hooks/pre-commit` (inverse of `install-hook`).

### 3. `changes --since <date or sync-comment>`
Filter changes by date or by the sync comment that created them.
```bash
caldb changes --since 2026-06-01
caldb changes --since "sprint 4 tuning"   # matches SyncComment prefix
```

### 4. `validate` command + validation integrated everywhere
A standalone `caldb validate` command checks all active parameters (or a pattern)
against their own `Min`/`Max`/`DataType` constraints:
```bash
caldb validate                   # check all active parameters
caldb validate -n "FanSpd*"      # subset
```
The same validation logic is reused as a warning (not a block) inside `add`, `update`,
`review`, and `sync` so a stale or out-of-range value is flagged wherever it first appears.
```
Warning: FanSpdReqMax value 150 exceeds Max 100 [uint8]
```

### 5. Shell completions
Click has built-in completion generation:
```bash
caldb --install-completion   # bash / zsh / fish
```

---

## Tier 2 — Medium effort, high payoff

### 6. `search` command
Find parameters by value, type, unit, source, or description keyword.
```bash
caldb search --datatype uint8
caldb search --source "App/FanCtl"
caldb search --description "timeout"
caldb search -n "FanSpd*"
```

### 7. `tag` command — snapshot labels
Mark a point in history with a name, like `git tag`.
```bash
caldb tag -n v1.2 -m "sprint 5 release candidate"
caldb tags                             # list all tags
caldb show -n TempCtlSetPnt --at v1.2  # value at a tagged point
```
Implementation: new `_caldb_tags` table with (name, ChangeDateTime, comment).

### 8. `restore` command
Revert a parameter's value to a previous state.
```bash
caldb restore -n TempCtlSetPnt              # to the value before last change
caldb restore -n TempCtlSetPnt --to-sync "initial import v0"
```
Writes a new history entry (`ChangeType='restore'`) so the rollback is tracked.

### 9. `stats` command
Quick summary of DB health and activity.
```
Parameters:   313 active, 4 deleted
Changes:      1 027 total (148 this month)
Most changed: TempCtlSetPnt (12), FanSpdMapX (9), PmpSpdMin (7)
Last sync:    2026-06-08 14:10  (in sync)
```

### 10. Export preserving original CSV format
Add `--format multicol` / `--format singlecol` to `export` so the output matches
the original column layout and opens correctly in Excel.

---

## Tier 3 — Larger features

### 11. `diff` and `merge` — cross-file and cross-DB comparison

Three related use cases sharing the same diff engine:

**History diff** — what changed between two tags or sync comments within one DB:
```bash
caldb diff --from "initial import v0" --to "sprint 5 release candidate"
```

**File diff** — compare two CSV files or a CSV against a DB snapshot.
A standalone Python script already exists for this; it will be promoted to a
first-class `caldb` subcommand:
```bash
caldb diff -f baseline.csv -f current.csv
caldb diff -f baseline.csv --db current.db
```

**Merge** — apply selected changes from one DB or CSV into another, with conflict detection:
```bash
caldb merge --from other.db          # preview what differs
caldb merge --from other.db --apply  # apply non-conflicting, prompt on conflicts
```

### 12. Multi-CSV tracking in one DB
Track several CSV files (e.g. per-subsystem calibration files) in a single `.db`.
- `caldb sync -f subsys_a.csv -f subsys_b.csv`
- `caldb changes --file subsys_a.csv` — scope history to one file

### 13. HTML / Markdown change report
```bash
caldb report -f report.html
caldb report --since "sprint 4" -f delta.md
```

### 14. Python API improvements
- Context manager: `with CalibrationDatabase('cal.db') as db:`
- `db.to_dataframe()` — returns a pandas DataFrame of active parameters
- `fields=` filter on `get_parameters()`

### 15. Parameter validation rules
Store per-parameter allowed-value lists or patterns in a `_caldb_rules` table.
```bash
caldb rule -n FanSpdReqMax --allowed "0,10,20,50,90,100"
```
Rules are checked on every `sync`/`add`/`update` and violations are flagged.
