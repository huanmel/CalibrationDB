# CalibrationDB

A lightweight tool for tracking per-parameter changes to calibration CSV files.

**What is a calibration file?**
A calibration file is a table of named parameters — constants and lookup tables
that control the runtime behaviour of an embedded system (thresholds, PID gains,
speed maps, timeouts, …). Each parameter has a value, a data type, units, limits,
and a description. Engineers iterate on these values throughout development and
tuning, so knowing *what changed, when, and why* is as important as the values
themselves.

**Why CSV + SQLite?**
CSV is the natural format for calibration data: it opens in Excel or any text
editor, it is human-readable, and it integrates cleanly with git for whole-file
versioning. A SQLite database sits alongside the CSV as a tracking layer — it
records every per-parameter change with timestamps, old/new values, and comments
without touching the CSV itself. JSON import is also supported when data comes
from automated tooling, but CSV remains the primary editing surface.

You keep editing your calibration CSV in Excel or a text editor as usual.
After each editing session, run `caldb sync` — it diffs the CSV against the
database, records what changed (added, modified, deleted parameters), and
stores the history with timestamps and optional comments.

Git tracks the file as a whole; CalibrationDB tracks each calibration
parameter individually — who changed what value, when, and why.

## Features

- **Two CSV formats** — auto-detected:
  - *Multi-column*: `Value_1 … Value_10` columns (one column per array element)
  - *Single-column*: `Value` with bracket notation `[0 80]` or `[0, 1, 2]`
- **Per-parameter change history** — every add, update, delete, and metadata change is logged
  with timestamp, old/new value, and an optional comment
- **Smart auto-detection** — if a `.db` and `.csv` share the same base name in
  the working directory, no path flags are needed
- **CLI with short flags** — `-n`, `-f`, `-c`, `-T`, … for quick use in a terminal
- **Soft delete** — removed parameters stay in history
- **Stale-DB warning** — any command that reads or edits the DB checks whether the CSV has changed since the last sync and warns if it has
- **Bidirectional sync** — `caldb sync --to-csv` writes CLI edits back to the CSV; direction is auto-detected
- **Metadata sync tracking** — when only non-value fields change (Unit, Min/Max, DataType, …) they are counted and recorded separately
- **Snapshot tags** — `caldb tag -n v1.2` marks a point in time; `caldb show --at v1.2` queries any parameter's value at that point; `--at DATETIME` back-dates a tag
- **Table output** — `caldb changes -T`, `caldb show -T`, `caldb search -T` for aligned, scannable tables
- **Search** — `caldb search -D "timeout"` finds parameters by description, datatype, unit, or source
- **Retroactive annotation** — `caldb annotate` lets you add or fix sync comments on past history entries
- **No server, no dependencies** beyond `click` — single SQLite file alongside your CSV

## Installation

```bash
git clone https://github.com/yourusername/calibrationdb.git
cd calibrationdb
pip install .
```

Or directly from GitHub:

```bash
pip install git+https://github.com/yourusername/calibrationdb.git
```

Requires Python ≥ 3.6 and `click ≥ 8.0`.

## Typical workflow

```
project/
  PROJECT_A_cal.csv   ← edit this in Excel or a text editor
  PROJECT_A_cal.db    ← created by caldb on first sync
```

**First sync — import the whole file:**
```bash
cd project/
caldb sync -c "initial import v0"
```

**After editing the CSV — record what changed:**
```bash
caldb sync -c "sprint 5 cold-weather tuning"
```

There are two complementary ways to annotate changes:

| Level         | Where                       | How                                             | Scope                                                              |
|---------------|-----------------------------|-------------------------------------------------|--------------------------------------------------------------------|
| Per-parameter | `COMMENT` column in the CSV | Edit the cell next to the parameter you changed | One row — why *this* value changed, its source, ticket number, etc.|
| Session       | `-c` flag on `sync`         | `caldb sync -c "sprint 5 tuning"`               | All changes in this sync — a batch label like a commit message     |

Both are stored in history. If you only ever use one, use the CSV `COMMENT` column — it travels with the file and gives the most useful context when reviewing old changes later.

**See what changed across all parameters:**
```bash
caldb changes          # last 10 changes
caldb changes -n 25    # last 25
caldb changes -n 0     # everything
caldb changes -t update   # only value changes
```

**See full history for one parameter:**
```bash
caldb log -n TempCtlSetPnt
```

Because the CSV and DB share the same base name, no `--db` or `--file` flags
are needed in any of the commands above.

## CSV formats

The tool auto-detects the format from the column headers.

### Multi-column

Arrays are spread across separate columns `Value_1` … `Value_10` (up to 10
elements). This is a common layout when calibration tables are exported from
tooling that keeps each element in its own column for easy spreadsheet editing:

```
Name,Value_1,Value_2,...,Value_10,COMMENT,DataType,Unit,Size,Min,Max,Description,Who,Users,Source
FanSpdReqMax,100,,,,,,,,,,,uint8,per,1,0,100,Maximum fan speed,ivan,,App/FanCtl
FanSpdMapX,0,20,40,60,80,100,,,,,,uint8,per,6,0,100,Speed map X axis,ivan,,App/FanCtl
```

### Single-column

Arrays are written as a bracketed list in a single `Value` column:

```
Name,Value,COMMENT,DataType,Unit,Size,Min,Max,Description,ALIASES
FanSpdReqMax,100,,uint8,per,1,0,100,Maximum fan speed,
FanSpdMapX,[0 20 40 60 80 100],,uint8,per,6,0,100,Speed map X axis,
```

Both `[0 80]` and `[0, 1, 2]` notation are accepted and stored identically,
so mixing formats never produces false change detections.

## CLI reference

All commands accept a global `--db / -d` flag.  When omitted, `caldb` looks
for a matched `.db` / `.csv` pair in the current directory.

```
caldb [--db FILE] [--test] COMMAND [OPTIONS]
```

`--test` rolls back every write — useful for a dry run of `add` / `update`.

---

### `validate` — check values against constraints

```bash
caldb validate                   # check all parameters
caldb validate -n "FanSpd*"      # subset by name/pattern
```

Output:
```
2 parameter(s) with violations:

  BadParam  (150)
    ! 150 > Max (100.0)
  WrongSize  (10 20)
    ! size: expected 4 element(s), got 2
```

Exits `0` if no violations, `1` if any found.
The same check runs automatically (as a non-blocking warning) inside `sync`, `add`, and `update`.

---

### `status` — check sync state between DB and CSV

```bash
caldb status
```

Output:
```
In sync  (last sync: 2026-06-09 10:14)
CSV changed since last sync (2026-06-09 10:14) -- run 'caldb sync'
DB changed via CLI (2026-06-09 10:22) -- run 'caldb sync --to-csv'
Both CSV and DB changed since last sync -- conflict, resolve manually
```

When either file has uncommitted git changes, extra lines are appended:

```text
CSV git:  modified (not staged)
DB  git:  staged for commit
```

Exit codes: `0` in sync · `1` CSV ahead · `2` DB ahead · `3` conflict · `4` never synced.
Useful in shell scripts: `caldb status || caldb sync`.

---

### `sync` — synchronise CSV and DB in either direction

```bash
caldb sync                          # auto-detect pair, no comment
caldb sync -c "sprint 5 tuning"     # attach a comment to all changes
caldb sync -f path/to/file.csv      # explicit CSV (DB derived from name)
caldb sync --dry-run                # show diff without writing
```

Output:

```text
Auto: PROJECT_A_cal.db / PROJECT_A_cal.csv
Sync: 2 added, 5 changed, 0 deleted, 1 meta updated (7 total)

CHANGED:
  ~ TempCtlSetPnt
  ~ FanSpdReqMax

META UPDATED:
  * FanSpdReqMax
```

When only non-value fields change (DataType, Unit, Min, Max, Description, …) they
appear in a separate `META UPDATED` count and section.  These changes are also
recorded in history with type `meta` and are visible in `caldb changes -t meta`.

**Bidirectional sync — writing DB changes back to the CSV:**

When parameters are edited via CLI (`add`, `update`, `delete`) the CSV falls
behind. `sync --to-csv` reverses the direction: it reads the current DB state
and patches the CSV in-place, preserving row order and column format.

```bash
caldb sync --to-csv                 # write DB changes back to CSV
caldb sync --to-csv --dry-run       # preview without writing
```

Direction is auto-detected when the flag is omitted:

| Situation                   | Auto-selected direction |
|-----------------------------|-------------------------|
| Only CSV changed            | CSV -> DB               |
| Only DB changed (CLI edits) | DB -> CSV               |
| Both changed                | Conflict — manual       |

When writing to CSV, each change is confirmed interactively:

```text
DB -> CSV: 0 to add, 2 to update

Confirm each change  (y=yes  n=skip  a=accept all  q=quit):

  UPDATE  FanSpdReqMax  (100 -> 90)
  [y/n/a/q] >
```

If the CSV has uncommitted git changes a warning is shown before any write.

---

### `diff` — show what differs between the CSV and the DB

Useful after `caldb status` reports a conflict (both sides changed since last
sync). Shows the DB value and CSV value side by side for every parameter that
differs, plus any parameters that exist only on one side.

```bash
caldb diff                          # compare auto-detected pair
caldb diff -f path/to/file.csv      # explicit CSV
caldb diff -n 'FanSpd*'            # filter by name / glob
```

Output:

```text
VALUE DIFFERS  (2 parameter(s)):

  FanSpdReqMax
    DB:   999
    CSV:  100
  FanSpdReqMin
    DB:   20
    CSV:  777

Summary: 2 value conflicts, 0 CSV-only, 0 DB-only  (2 total differences)
```

To resolve a conflict shown by `diff`:

- `caldb sync` — accept CSV values (overwrites CLI edits in DB)
- `caldb sync --to-csv` — accept DB values (overwrites CSV edits)

---

### `review` — interactively confirm changes before writing

Like `sync`, but steps through each change one at a time so you can add a
per-parameter comment and decide whether to apply it.

```bash
caldb review                       # auto-detect pair
caldb review -f path/to/file.csv
```

For each change:

```
--- [2/5]  UPDATE  TempCtlSetPnt
    value:    22.5  ->  24.0
    comment > cold weather target
```

| Input    | Action                                            |
|----------|---------------------------------------------------|
| Enter    | confirm, no comment                               |
| `<text>` | confirm with that text as the change comment      |
| `s`      | skip — do not apply this change                   |
| `q`      | stop reviewing, apply everything confirmed so far |
| `a`      | abort — apply nothing                             |

---

### `show` — current value and metadata

```bash
caldb show                        # all parameters (detailed)
caldb show -n TempCtlSetPnt       # one parameter
caldb show -n "FanSpd*"           # glob pattern
caldb show -n "FanSpd*" -c        # compact: one line per parameter
caldb show -T                     # aligned table (all parameters)
caldb show --at v1.2              # all parameters as they were at a tag
caldb show -n TempCtlSetPnt --at v1.2   # single parameter at a tag
```

Detailed output:

```text
TempCtlSetPnt
  value:    22.5
  type:     single, degC, size=1
  range:    -10.0 .. 50.0
  desc:     Cabin temperature set point
  comment:  cold weather target
  who/src:  ivan  /  App/ClimCtl
```

Compact output (`-c`):

```text
FanSpdMapX=0 20 40 60 80 100
FanSpdReqMax=100
FanSpdReqMin=20
```

When `--at <tag>` is given, values and comments are reconstructed from history
at the tag timestamp.  Metadata (type, range, description) always reflects the
current state since those fields are not tracked per-change.

---

### `search` — find parameters by metadata

```bash
caldb search -D "timeout"           # description contains "timeout"
caldb search -D "*derate*"          # description glob
caldb search -D "speed" -t uint8    # description AND datatype (AND-ed)
caldb search -s "App/FanCtl"        # by source module
caldb search -u "rpm" -c            # by unit, compact output
caldb search -n "*Map*" -D "axis"   # name glob AND description
caldb search -D "speed" -T          # aligned table output
```

All filters are AND-ed.  Plain strings match as substrings; `*` and `?` work
as wildcards.  Options: `-n` name · `-D` description · `-t` datatype ·
`-u` unit · `-s` source · `-c` compact output · `-T` table output.

---

### `tag` — create a snapshot label

```bash
caldb tag -n v1.2 -m "sprint 5 release candidate"
caldb tag -n pre-tuning                            # message is optional
caldb tag -n v1.0 --at "2026-06-08 14:06:47"      # back-date to a past timestamp
```

Tags record a timestamp so any parameter's value can be queried at that point
later with `caldb show --at <tag>`.  Use `--at` to place a tag at a past point
(e.g. to label a sync session that happened before you started tagging).

---

### `tags` — list all snapshot labels

```bash
caldb tags
```

Output:

```text
2 tag(s):

  2026-06-08 14:10:55  v1.0  baseline after initial import
  2026-06-09 09:30:00  v1.1  sprint 1 tuning
```

---

### `changes` — recent changes across all parameters

```bash
caldb changes                        # last 10 (default)
caldb changes -n 25                  # last 25
caldb changes -n 0                   # all
caldb changes -t update              # filter: add | update | delete | restore | meta
caldb changes -s 2026-06-01          # on or after a date
caldb changes -s "sprint 4 tuning"   # on or after the sync with that -c comment
caldb changes -c                     # compact: one line per change
caldb changes -T                     # aligned table
caldb changes --by-tag               # group changes between tag milestones (all entries)
caldb changes --by-tag -T -n 25      # table view, capped at 25 entries per run
caldb changes --no-tags              # hide interleaved tag markers
```

Detailed output (tags are interleaved as markers, like `git log --oneline`):
```
5 change(s) (last 10):

  2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  [sprint 5 tuning]
           value:   22.5  ->  24.0
  ---- tag: v1.1  "sprint 5 baseline" ----
  2026-06-08 14:10:55  ADD     PmpSpdMin  [initial import v0]
           value:   500
```

Compact output (`-c`):
```
2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  22.5 -> 24.0  [sprint 5 tuning]
2026-06-08 14:10:56  UPDATE  FanSpdReqMax  100 -> 90  [sprint 5 tuning]
2026-06-08 14:10:55  ADD     PmpSpdMin  500  [initial import v0]
```

Table output (`-T`):
```
DateTime             Type     Name            Old Value  New Value  Comment
---------------------------------------------------------------------------
2026-06-08 14:10:56  UPDATE   TempCtlSetPnt   22.5       24.0       sprint 5 tuning
2026-06-08 14:10:56  UPDATE   FanSpdReqMax    100        90         sprint 5 tuning
```

`--by-tag` output groups changes between consecutive tags:
```
After v1.1:
  2026-06-08 ...  UPDATE  TempCtlSetPnt  22.5 -> 24.0  [sprint 5 tuning]

v1.0..v1.1  "sprint 5 baseline":
  2026-06-08 ...  ADD     FanSpdMapX  0 20 40 60 80 100  [initial import]
```

`-n` limits apply per run; omit `-n` with `--by-tag` to see all entries grouped.

---

### `log` — history for one parameter

```bash
caldb log -n TempCtlSetPnt        # last 20 entries (default)
caldb log -n TempCtlSetPnt -l 5   # last 5
```

Output:
```
History for 'TempCtlSetPnt' (2 entries):

  2026-06-08 14:10:56  UPDATE  [sprint 5 tuning]
    value:   22.5  ->  24.0
  2026-06-08 14:10:55  ADD  [initial import v0]
    value:   22.5
```

---

### `add` — add a single parameter via CLI

```bash
caldb add -n FanSpdRateLim -v 10 --datatype uint8 --unit "per/s" --size 1 \
          -m "rate limiter added in sprint 5"
```

---

### `update` — change the value of a parameter

```bash
caldb update -n PmpSpdMin -v 600 -m "raised idle speed to avoid stall"
```

---

### `rename` — rename a parameter (old name kept as alias)

```bash
caldb rename -i OldParamName --new-name NewParamName -m "renamed per naming convention"
```

---

### `delete` — soft-delete a parameter (kept in history)

```bash
caldb delete -n FaultRecovTout -c "merged into FaultTout"
```

---

### `load` — bulk-import from CSV or JSON (no change tracking)

```bash
caldb load                          # auto-detect CSV
caldb load -f params.csv
caldb load -f params.json
```

> Use `sync` instead of `load` when you want changes recorded in history.

---

### `export` — export DB to CSV

```bash
caldb export                        # writes <dbname>.csv
caldb export -f output.csv
```

---

### `annotate` — retroactively label history entries

Add or fix the sync comment on history entries that were synced without a `-c`
flag, or whose label you want to update.

```bash
# Label all changes from a sync session (by start timestamp)
caldb annotate -m "sprint 5 baseline" -s "2026-06-08 14:10"

# Label a specific time window
caldb annotate -m "hot fix" -s "2026-06-10 09:00" -u "2026-06-10 10:00"

# Annotate one row by its history id (get ids from caldb log)
caldb annotate -m "corrected unit" --id 42

# Preview which rows would be updated before writing
caldb annotate -m "sprint 5" -s "2026-06-08" --dry-run
```

`--dry-run` output:

```text
[DRY RUN] Would annotate 4 row(s) with: "sprint 5 baseline"

    1  2026-06-08T14:10:55  add     FanSpdReqMax  (was: "initial import")
    2  2026-06-08T14:10:55  add     FanSpdMapX    (was: "initial import")
```

The `--since` / `--until` window uses the stored ISO timestamps.  Both `T` and
space separators are accepted (`"2026-06-08T14:10"` and `"2026-06-08 14:10"` are
equivalent).

---

### `install-hook` — auto-sync on every git commit

Writes a `pre-commit` hook into the current repository so that `caldb sync`
runs automatically whenever you commit a CSV file.  The hook only fires for
CSV files that are actually staged — unrelated commits are not affected.  If a
`pre-commit` hook already exists the caldb block is appended to it.

```bash
cd project/           # must be inside a git repo
caldb install-hook
```

After installation, the typical commit flow becomes:

```bash
# Edit PROJECT_A_cal.csv in Excel
git add PROJECT_A_cal.csv
git commit -m "sprint 5 cold-weather tuning"
# pre-commit hook runs caldb sync automatically,
# stages PROJECT_A_cal.db, and includes it in the commit
```

---

## Auto-detection rules

| `--db`   | `--file`  | DB used                           | CSV used       |
|----------|-----------|-----------------------------------|----------------|
| omitted  | omitted   | matched `.db`/`.csv` pair in cwd  | same base name |
| `foo.db` | omitted   | `foo.db`                          | `foo.csv`      |
| omitted  | `foo.csv` | `foo.db` (must exist)             | `foo.csv`      |
| `foo.db` | `bar.csv` | `foo.db`                          | `bar.csv`      |

If multiple pairs exist in the directory, `--db` is required.

---

## Programmatic API

```python
from calibrationdb.cal_db_util import CalibrationDatabase, CalibrationParameter

db = CalibrationDatabase('PROJECT_A_cal.db')

# Sync from CSV and record changes
added, changed, deleted = db.sync_from_csv(
    'PROJECT_A_cal.csv',
    sync_comment='sprint 5 tuning',
)

# Write DB changes back to CSV (bidirectional sync)
diff = db.compute_db_to_csv_diff('PROJECT_A_cal.csv')
db.write_back_to_csv('PROJECT_A_cal.csv', diff)
db.store_csv_hash('PROJECT_A_cal.csv')   # clears db_changed flag

# Current parameter values
for row in db.get_parameters():          # all
    print(row['Name'], row['Value'])

for row in db.get_parameters('FanSpd*'): # glob
    print(row['Name'], row['Value'])

# Search by metadata
for row in db.search_parameters(description='timeout', datatype='uint16'):
    print(row['Name'], row['Value'])

# History for one parameter
for entry in db.get_parameter_log('TempCtlSetPnt'):
    print(entry['ChangeDateTime'], entry['ChangeType'], entry['NewValue'])

# Recent changes across all parameters
for entry in db.get_recent_changes(limit=10, since='sprint 4 tuning'):
    print(entry['Name'], entry['ChangeType'], entry['OldValue'], '->', entry['NewValue'])

# Tags
db.tag_snapshot('v1.2', comment='sprint 5 release candidate')
for t in db.list_tags():
    print(t['name'], t['ChangeDateTime'], t['comment'])

# Parameter values at a tagged point
tag_time, rows = db.get_parameters_at_tag('v1.2', pattern='FanSpd*')
for row in rows:
    print(row['Name'], row['Value'])

# Sync state
in_sync, last_sync_time = db.get_sync_status('PROJECT_A_cal.csv')
db_changed_time = db.get_db_changed_time()   # None if no CLI edits since sync

db.close()
```

## Project structure

```text
calibrationdb/
├── src/calibrationdb/
│   ├── __init__.py
│   ├── cal_db_util.py      # CalibrationDatabase class
│   └── cal_db_cli.py       # CLI (click)
├── example/
│   ├── example_cal.csv     # sample multi-column CSV (12 parameters)
│   └── run_example.ps1     # full workflow walkthrough (PowerShell)
├── data/
│   └── example_cals.csv    # sample single-column CSV (28 parameters)
├── pyproject.toml
├── ROADMAP.md
└── README.md
```

## Roadmap

Remaining planned features — `restore`, `stats`, `diff`, `merge`, shell completions,
and more — are tracked in [ROADMAP.md](ROADMAP.md).

## License

MIT
