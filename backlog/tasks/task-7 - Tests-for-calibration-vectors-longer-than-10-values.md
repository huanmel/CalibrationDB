---
id: TASK-7
title: Tests for calibration vectors longer than 10 values
status: Done
assignee: []
created_date: 2026-10-22 09:03
updated_date: '2026-11-02T15:37:00Z'
labels:
  - tests
dependencies: []
type: task
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Commit 92de356 added support for calibration vectors longer than 10 values (dp187 needs 16-element masks): value columns are read from the CSV header (_value_cols), write-back adds Value_N columns after the last existing one when a vector is longer, and _split_to_value_cols raises instead of truncating. The repo has no test suite, so this behaviour is only covered by an external script in the dp187_csw project (work/task126 / t127_compat.py). Add regression tests in this repo.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Test: a 16-value calibration is read with all values (columns taken from the header)
- [x] #2 Test: sync/write-back into a 10-column CSV adds Value_11..Value_16 after the last value column, before the metadata columns (COMMENT etc.)
- [x] #3 Test: Size larger than the available value columns raises an error, no silent truncation
- [x] #4 Test: an existing 10-column CSV gives the same result as before (no extra columns written)
- [x] #5 Test: a change only in value 14 is detected by status/sync and recorded in the history
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
This is the repo's first test suite (ROADMAP.md item A already specifies pytest + click.testing.CliRunner -- following that, not introducing a new framework). Scope: only the 5 ACs for commit 92de356 (vectors >10 values), not the full roadmap item A.

1. Add pytest as a dev/test dependency group in pyproject.toml ([project.optional-dependencies] test = ["pytest"]). No other new deps needed -- CliRunner ships with click, which is already a dependency.
2. Create tests/ at repo root (sibling to src/), with a conftest.py providing two fixtures:
   - a tmp_path-based CalibrationDatabase (real sqlite file, not :memory:, matching real usage)
   - a helper to write a multi-column CSV fixture file with a given header/row, matching the real format confirmed in example/example_cal.csv (Name,Value_1..Value_N,COMMENT,DataType,Unit,Size,Min,Max,Description,Who,Users,Source -- metadata columns after the Value_N columns).
3. tests/test_multicol_values.py, one test per AC, exercising CalibrationDatabase/_load_csv_params/_value_cols/_split_to_value_cols directly (per ROADMAP's "Priority areas" -- unit-level on cal_db_util.py, not CLI subprocess calls):
   - AC1: 16-value row read via _load_csv_params / _parse_multicol_row -- assert param.value has all 16 space-separated values (not truncated to 10).
   - AC2: load a 10-column CSV into a DB, change a value to 16 elements via the DB (simulating a CLI update), then db.write_back_to_csv -- assert the CSV header gained Value_11..Value_16 positioned right after Value_10 and before COMMENT, and the row's new columns hold the right values.
   - AC3: _split_to_value_cols raises ValueError (not silent truncation) when canonical.split() has more elements than len(value_cols) -- also exercise it through write_back_to_csv with a value longer than CSV columns support where n_need computation still leaves a shortfall, to pin the no-truncation contract end to end if feasible, else unit-level on _split_to_value_cols alone.
   - AC4: write_back_to_csv against an existing 10-column CSV with all values <=10 elements -- assert fieldnames/header unchanged (no Value_11+ added).
   - AC5: load a 16-value CSV into a DB via sync_from_csv, edit only element 14 in the CSV, run sync_from_csv again -- assert compute_diff/sync detects exactly that parameter as changed and calibration_history (via get_parameter_log) records an 'update' row with the right old/new values.
4. Run `pytest` locally against the editable install; fix any failures found (this is new code path territory -- a real bug surfacing here is in scope to fix, per task-execution's normal loop).
5. Update ROADMAP.md item A to note the multicol regression tests now exist (brief, not a rewrite).
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added pytest as a test extra (pyproject.toml [project.optional-dependencies] test = ["pytest>=7.0"]) -- this is the repo's first test suite, matching ROADMAP.md item A's already-stated choice of pytest (+ CliRunner for CLI tests, not needed for this task since all 5 ACs exercise cal_db_util.py directly per the roadmap's own "priority areas" guidance).

Created tests/conftest.py (db fixture: tmp_path-backed CalibrationDatabase; multicol_csv_writer fixture: writes a Name,Value_1..Value_N,COMMENT,DataType,Unit,Size,Min,Max,Description,Who,Users,Source CSV, matching the real header order confirmed in example/example_cal.csv) and tests/test_multicol_values.py with one test per AC:
- AC1 test_multicol_read_all_values: _load_csv_params on a 16-value row returns all 16 space-separated values.
- AC2 test_writeback_extends_columns_for_longer_vector: update a param to 16 elements, write_back_to_csv against the original 10-column CSV -- asserts Value_11..Value_16 inserted right after Value_10 and before COMMENT, with correct per-column values.
- AC3 test_split_to_value_cols_raises_instead_of_truncating: unit test on _split_to_value_cols directly (4 values into 3 columns) -- asserts ValueError (not truncation) and that the row dict stays untouched (the length check runs before any mutation).
- AC4 test_writeback_unchanged_header_when_values_fit: values that fit in 10 columns leave the header unchanged after write_back_to_csv.
- AC5 test_sync_detects_change_deep_in_long_vector: sync a 16-value CSV, edit only element 14, sync again -- asserts sync_from_csv reports exactly that parameter changed and calibration_history (get_parameter_log) records the update with correct old/new values.

All 5 tests pass on the first run (`pytest -m pip install -e ".[test]"` then `pytest tests/ -v`, 5 passed) -- commit 92de356's fix works as intended, no bugs found. Updated ROADMAP.md item A and CLAUDE.md to note the test suite now exists (both previously said "no test suite exists").
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added the repo's first test suite (pytest, per ROADMAP.md item A) with regression coverage for commit 92de356 (calibration vectors longer than 10 values): tests/conftest.py + tests/test_multicol_values.py, one test per acceptance criterion, all passing against the real cal_db_util.py code paths (_load_csv_params, write_back_to_csv, _split_to_value_cols, sync_from_csv/get_parameter_log). pyproject.toml gained a `test` extra for pytest. No bugs found -- the existing fix already behaves correctly on all 5 fronts (full read, column-growing write-back, raise-not-truncate, unchanged header when nothing grows, and detecting+recording a change buried at element 14 of 16). ROADMAP.md and CLAUDE.md updated to reflect that a tests/ directory now exists (most of item A's other priority areas -- CLI integration, tag/restore round-trips -- remain open, left as future work, not expanded here).
<!-- SECTION:FINAL_SUMMARY:END -->
