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
- **Per-parameter change history** — every add, update, and delete is logged
  with timestamp, old/new value, and an optional comment
- **Smart auto-detection** — if a `.db` and `.csv` share the same base name in
  the working directory, no path flags are needed
- **CLI with short flags** — `-n`, `-f`, `-c`, `-p`, … for quick use in a terminal
- **Soft delete** — removed parameters stay in history
- **Stale-DB warning** — any command that reads or edits the DB checks whether the CSV has changed since the last sync and warns if it has
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

Exit codes: `0` in sync · `1` CSV ahead · `2` DB ahead · `3` conflict · `4` never synced.
Useful in shell scripts: `caldb status || caldb sync`.

---

### `sync` — diff CSV → DB and record all changes

```bash
caldb sync                          # auto-detect pair, no comment
caldb sync -c "sprint 5 tuning"     # attach a comment to all changes
caldb sync -f path/to/file.csv      # explicit CSV (DB derived from name)
caldb sync --dry-run                # show diff without writing
```

Output:
```
Auto: PROJECT_A_cal.db / PROJECT_A_cal.csv
Sync: 2 added, 5 changed, 0 deleted (7 total)

CHANGED:
  ~ TempCtlSetPnt
  ~ FanSpdReqMax
  ...
```

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
```

Detailed output:
```
TempCtlSetPnt
  value:    22.5
  type:     single, degC, size=1
  range:    -10.0 .. 50.0
  desc:     Cabin temperature set point
  comment:  cold weather target
  who/src:  ivan  /  App/ClimCtl
```

Compact output (`-c`):
```
FanSpdMapX=0 20 40 60 80 100
FanSpdReqMax=100
FanSpdReqMin=20
```

---

### `changes` — recent changes across all parameters

```bash
caldb changes                        # last 10 (default)
caldb changes -n 25                  # last 25
caldb changes -n 0                   # all
caldb changes -t update              # filter: add | update | delete
caldb changes -s 2026-06-01          # on or after a date
caldb changes -s "sprint 4 tuning"   # on or after a named sync session
caldb changes -c                     # compact: one line per change
```

Detailed output:
```
5 change(s) (last 10):

  2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  [sprint 5 tuning]
           value:   22.5  ->  24.0
  2026-06-08 14:10:56  UPDATE  FanSpdReqMax  [sprint 5 tuning]
           value:   100  ->  90
  2026-06-08 14:10:55  ADD     PmpSpdMin  [initial import v0]
           value:   500
```

Compact output (`-c`):
```
2026-06-08 14:10:56  UPDATE  TempCtlSetPnt  22.5 -> 24.0  [sprint 5 tuning]
2026-06-08 14:10:56  UPDATE  FanSpdReqMax  100 -> 90  [sprint 5 tuning]
2026-06-08 14:10:55  ADD     PmpSpdMin  500  [initial import v0]
```

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
from calibrationdb import CalibrationDatabase, CalibrationParameter

db = CalibrationDatabase('PROJECT_A_cal.db')

# Sync from CSV and record changes
added, changed, deleted = db.sync_from_csv(
    'PROJECT_A_cal.csv',
    sync_comment='sprint 5 tuning',
)

# History for one parameter
for entry in db.get_parameter_log('TempCtlSetPnt'):
    print(entry['ChangeDateTime'], entry['ChangeType'], entry['NewValue'])

# Recent changes across all parameters
for entry in db.get_recent_changes(limit=10):
    print(entry['Name'], entry['ChangeType'], entry['OldValue'], '->', entry['NewValue'])

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

Planned features — `status`, `validate`, `search`, `tag`, `restore`, `diff`, `merge`,
and more — are tracked in [ROADMAP.md](ROADMAP.md).

## License

MIT
