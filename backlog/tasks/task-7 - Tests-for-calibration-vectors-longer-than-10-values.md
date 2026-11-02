---
id: TASK-7
title: Tests for calibration vectors longer than 10 values
status: To Do
assignee: []
created_date: '2026-10-22 09:03'
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
- [ ] #1 Test: a 16-value calibration is read with all values (columns taken from the header)
- [ ] #2 Test: sync/write-back into a 10-column CSV adds Value_11..Value_16 after the last value column, before the metadata columns (COMMENT etc.)
- [ ] #3 Test: Size larger than the available value columns raises an error, no silent truncation
- [ ] #4 Test: an existing 10-column CSV gives the same result as before (no extra columns written)
- [ ] #5 Test: a change only in value 14 is detected by status/sync and recorded in the history
<!-- AC:END -->
