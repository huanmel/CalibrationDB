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
- **Flexible diff** — `caldb diff` compares CSV vs DB, two CSV files directly, or two tags/dates/sync comments; `-T` for a colorized table view
- **Table output by default** — `caldb log`, `caldb show` print an aligned table; pass `--detail`/`-v` for the old multi-line view
- **Search** — `caldb show -D "timeout"` finds parameters by description, datatype, unit, or source
- **Retroactive annotation** — `caldb annotate` lets you add or fix sync comments on past history entries
- **No server** — single SQLite file alongside your CSV; CLI built on `click`/`typer`, with `rich` for colorized table output

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

**First sync — creates the DB and imports everything:**
```bash
cd project/
caldb sync -f PROJECT_A_cal.csv -c "initial import v0"
# Creating DB: PROJECT_A_cal.db
# Sync: 42 added, 0 changed, 0 deleted (42 total)
```

The `.db` is created automatically — no setup step needed.

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
caldb log               # last 10 changes
caldb log -n 25         # last 25
caldb log -n 0          # everything
caldb log -t update     # only value changes
```

**See full history for one parameter:**
```bash
caldb log TempCtlSetPnt
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
caldb sync -f my_cal.csv -c "initial import"   # first use: creates the DB
caldb sync                          # auto-detect pair (after first sync)
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
recorded in history with type `meta` and are visible in `caldb log -t meta`.

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

### `diff` — compare two snapshots of the calibration data

Default mode is useful after `caldb status` reports a conflict (both sides
changed since last sync): shows the DB value and CSV value side by side for
every parameter that differs, plus any parameters that exist only on one
side, and any metadata-only changes (Unit, Min/Max, Description, Source, …
changed but the value didn't). Two extended modes let you compare things
other than "current CSV vs current DB":

```bash
caldb diff                                     # compare auto-detected CSV vs DB
caldb diff -f path/to/file.csv                 # explicit CSV vs DB
caldb diff -n 'FanSpd*'                        # filter by name / glob
caldb diff -T                                  # colorized table view (one row per parameter)

# Extended: two CSV files directly, no DB
caldb diff -f baseline.csv -f current.csv

# Extended: two point-in-time snapshots (tag name, date, or sync comment)
caldb diff --from v1.0 --to v1.2               # between two tags
caldb diff --from v1.0                         # a tag vs the current state
caldb diff --from 2026-06-01 --to 2026-06-10   # between two dates
caldb diff --from "sprint 4 tuning"            # a sync comment resolves like `log --since`
```

Plain output:

```text
VALUE DIFFERS  (2 parameter(s)):

  FanSpdReqMax
    DB:   999
    CSV:  100
  FanSpdReqMin
    DB:   20
    CSV:  777

METADATA CHANGED  (1 parameter(s), value unchanged):

  PmpSpdMin
    Source: App/PmpCtl -> App/PmpCtl_v2

Summary: 2 value conflicts, 1 metadata-only, 0 CSV-only, 0 DB-only  (3 total differences)
```

Table output (`-T`), colorized by change type — the same `UPDATE`/`ADD`/
`DELETE`/`META` vocabulary and colors as `caldb log`:

```text
Type    Name           DB    CSV
--------------------------------
UPDATE  FanSpdReqMax   999   100
UPDATE  FanSpdReqMin   20    777
META    PmpSpdMin            Source: App/PmpCtl -> App/PmpCtl_v2
```

For `--from`/`--to`, metadata isn't reconstructed per snapshot the way Value
is (DataType/Unit/Min/Max/Description/Source always reflect *today's*
metadata, not the tag's) — metadata-only changes in that mode instead come
from the `'meta'` history entries recorded in the time window between the
two refs, so they still show up correctly even though the two reconstructed
snapshots' metadata columns are identical.

To resolve a conflict shown by the default `diff`:

- `caldb sync` — accept CSV values (overwrites CLI edits in DB)
- `caldb sync --to-csv` — accept DB values (overwrites CSV edits)

Saving a diff to a file for later use (e.g. as an update source) isn't built
yet — tracked as `diff --export` in [ROADMAP.md](ROADMAP.md).

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

### `show` — current value and metadata, by name or by search filter

```bash
caldb show                        # all parameters (table)
caldb show TempCtlSetPnt          # one parameter (exact name, positional)
caldb show "FanSpd*"              # glob pattern
caldb show "FanSpd*" -c           # compact: one line per parameter
caldb show --detail                # old multi-line detailed view (short: -v)
caldb show --at v1.2              # all parameters as they were at a tag
caldb show TempCtlSetPnt --at v1.2   # single parameter at a tag

caldb show -D "timeout"           # description contains "timeout" (table output)
caldb show -D "*derate*"          # description glob
caldb show -D "speed" -t uint8    # description AND datatype (AND-ed)
caldb show -s "App/FanCtl"        # by source module
caldb show -u "rpm" -c            # by unit, compact output
caldb show "*Map*" -D "axis"      # name glob AND description
caldb show -D "speed" --detail    # old multi-line detailed output
```

NAME is exact-match unless it contains `*`/`?` (glob). `-D`/`-t`/`-u`/`-s` are substring
matches unless they contain a wildcard too; all given filters are AND-ed. `--at` can only
be combined with NAME, not with `-D`/`-t`/`-u`/`-s`.

Options: NAME (positional) · `-D` description · `-t` datatype · `-u` unit · `-s` source ·
`-c` compact output · table output is the default ·
`--detail`/`-v` for the old multi-line view · `--at TAG` for a point-in-time snapshot.

Table is the default view. Detailed output (`--detail`/`-v`):

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

### `log` — change history, across all parameters or for one

Modeled on `git log [<path>] [options]`: omit the parameter name for changes across everything,
or pass one to see just that parameter's history. NAME is exact-match unless it contains a
glob wildcard (`*` or `?`), matching the same convention as `caldb show`.

```bash
caldb log                            # last 10, all parameters, table view (default)
caldb log TempCtlSetPnt              # last 10 entries for one parameter
caldb log "FanSpd*"                  # last 10 across matching parameters
caldb log TempCtlSetPnt -n 0         # full history for one parameter
caldb log -n 25                      # last 25, all parameters
caldb log -n 0                       # all
caldb log -t update                  # filter: [add|update|delete|restore|meta]
caldb log -s 2026-06-01              # on or after a date
caldb log -s "sprint 4 tuning"       # on or after the sync with that -c comment
caldb log -v -c                      # compact: one line per change (short for --detail)
caldb log -v                         # old multi-line detailed view, tags interleaved
caldb log --by-tag                   # group changes between tag milestones (all entries)
caldb log --by-tag -n 25             # table view per section, capped at 25 entries per run
caldb log -v --no-tags               # hide interleaved tag markers (detailed view only)
```

Table output, all parameters (default):
```
DateTime             Type     Name            Old Value  New Value  Comment
---------------------------------------------------------------------------
2026-06-08 14:10:56  UPDATE   TempCtlSetPnt   22.5       24.0       sprint 5 tuning
2026-06-08 14:10:56  UPDATE   FanSpdReqMax    100        90         sprint 5 tuning
```

Table output, one parameter (`caldb log TempCtlSetPnt`) — prints a header line first:
```
History for 'TempCtlSetPnt' (2 entries):

DateTime             Type     Name           Old Value  New Value  Comment
--------------------------------------------------------------------------
2026-06-08 14:10:56  UPDATE   TempCtlSetPnt  22.5       24.0       sprint 5 tuning
2026-06-08 14:10:55  ADD      TempCtlSetPnt             22.5       initial import v0
```

Detailed output (`--detail`/`-v`; tags are interleaved as markers, like `git log --oneline`):
```
5 change(s) (last 10):

  2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  [sprint 5 tuning]
           value:   22.5  ->  24.0
  ---- tag: v1.1  "sprint 5 baseline" ----
  2026-06-08 14:10:55  ADD     PmpSpdMin  [initial import v0]
           value:   500
```

Compact output (`--detail -c` / `-v -c`; `-c` only takes effect together with `--detail`, since
table is otherwise the default view):
```
2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  22.5 -> 24.0  [sprint 5 tuning]
2026-06-08 14:10:56  UPDATE  FanSpdReqMax  100 -> 90  [sprint 5 tuning]
2026-06-08 14:10:55  ADD     PmpSpdMin  500  [initial import v0]
```

`--by-tag` output groups changes between consecutive tags (table per section by default; add
`--detail`/`-v` for the older compact-per-line grouping):
```
After v1.1:
  2026-06-08 ...  UPDATE  TempCtlSetPnt  22.5 -> 24.0  [sprint 5 tuning]

v1.0..v1.1  "sprint 5 baseline":
  2026-06-08 ...  ADD     FanSpdMapX  0 20 40 60 80 100  [initial import]
```

`-n` limits apply per run; omit `-n` with `--by-tag` to see all entries grouped. `-v` is
short for `--detail`; table is always the default view otherwise.

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
| omitted  | `foo.csv` | `foo.db` (created if needed¹)     | `foo.csv`      |
| `foo.db` | `bar.csv` | `foo.db`                          | `bar.csv`      |

If multiple pairs exist in the directory, `--db` is required.

¹ `sync` and `load` create the DB automatically when it doesn't exist yet.
All other commands require an existing DB.

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

Remaining planned features — `diff --export`, `merge`, `stats`, shell completions,
and more — are tracked in [ROADMAP.md](ROADMAP.md).

## License

MIT
