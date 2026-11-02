---
id: TASK-6
title: print pretty log with colored diff
status: Done
assignee: []
created_date: 2026-10-21 07:47
updated_date: '2026-11-02T15:24:00Z'
labels: []
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
lets print diff values highlighted so it would be clear what was changed
also would be good to print comments in their columns not in new lines from left
for example
(ekl_work) PS ...data> caldb log -n 100 --by-tag -t update
Using DB:XXX_cal.db
After v1.0.0:
  DateTime    Name             Old Value    New Value    Comment                                                                                                                   
  ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
  2026-10-    CalibrationParam 1 1 1 1 1    1 1 1 0 1    SomeLongTextxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 In caldb log's table view, the differing element(s) between Old Value and New Value are visually highlighted for UPDATE/RESTORE rows (array values highlight just the changed element(s); scalars highlight the whole value)
- [x] #2 The Comment column is truncated to a fixed width so long sync comments never push the row past one line / break terminal alignment, consistent with how Old/New Value are already truncated
- [x] #3 Existing row-level coloring by change type (ADD/DELETE/UPDATE/RESTORE/META) is preserved, and caldb show / caldb diff -T still render correctly
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Fix 1 -- cap the Comment column: in _print_changes_table (cal_db_cli.py), truncate SyncComment via _trunc(sc, _MAX_SC=30), matching the Old/New Value truncation already applied there.
2. Fix 2 -- highlight the differing element(s) between Old/New Value for UPDATE/RESTORE rows: add _trunc_text() and _highlight_diff_pair() helpers using rich.text.Text (not markup strings, to avoid literal [ ] in values being misparsed), tokenizing via cal_db_util._canonicalise_value for element-wise array comparison (bold red=old token, bold green=new token); scalar/mismatched-arity values fall back to highlighting the whole value.
3. Loosen _print_table's cell-building from str(x) to passing values through as-is, so Text objects keep their styling (verified no other call site -- show/diff -- ever puts a non-string into a row dict).
4. Add imports: _canonicalise_value from .cal_db_util, Text from rich.text.
5. Scope: caldb log (_print_changes_table) only, confirmed with user -- NOT caldb diff -T (_print_diff_table), which has the same column shape but is explicitly out of scope / a possible follow-up.
6. Verify against example/example.db: scalar UPDATE highlight, array UPDATE with one differing element, long sync comment truncation, and the task's own 'caldb log --by-tag -t update' scenario. Spot-check show/diff -T still render.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Verified against example/example.db (test mutations reverted afterward, git status clean):
- AC1: raw-byte capture (forcing a terminal + color system, bypassing this sandbox's NO_COLOR=1) confirmed exact ANSI spans: for array UPDATE '10 20 40 70 90 100' -> '10 20 40 99 90 100', only element 4 got '\x1b[1;31m70\x1b[0m' (old, bold red) / '\x1b[1;32m99\x1b[0m' (new, bold green); the other 5 elements were plain. Scalar UPDATE (22.5 -> 24.0) highlights the whole value since there's only one token.
- AC2: added a parameter update with an 88-char comment; caldb log rendered it truncated to 30 chars with trailing '~', row stayed on one line (no terminal soft-wrap misalignment). Ran the task's exact repro command 'caldb log --by-tag -t update' and confirmed clean alignment.
- AC3: caldb show and caldb diff -T (both go through the same _print_table whose cell-building was loosened from str(x) to passing values through) still render correctly -- spot-checked both.
Scope: per discussion, this only touches _print_changes_table (caldb log). _print_diff_table (caldb diff -T) has the same Old/New Value column shape and could reuse _highlight_diff_pair later, but that's an explicit follow-up, not done here.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
caldb log's table view now highlights exactly which element(s) differ between Old Value and New Value (bold red/green, standard diff colors) for UPDATE/RESTORE rows -- array values highlight just the changed element(s) via the same tokenization _canonicalise_value already uses elsewhere for comparisons; scalars highlight the whole value. The Comment column is now truncated to 30 chars (matching the precedent already used for Old/New Value and for show's Description/Comment columns), fixing the terminal soft-wrap misalignment shown in the task's pasted example. Implemented with rich.text.Text objects (not hand-built markup strings) to avoid any risk of literal brackets in stored values being misparsed as markup. Scoped to caldb log only (not caldb diff -T, which has the same column shape but was explicitly left out per discussion -- candidate for a follow-up task). Only src/calibrationdb/cal_db_cli.py changed.
<!-- SECTION:FINAL_SUMMARY:END -->
