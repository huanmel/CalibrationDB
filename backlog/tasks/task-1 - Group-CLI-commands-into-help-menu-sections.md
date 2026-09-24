---
id: TASK-1
title: Group CLI commands into help-menu sections
status: Done
assignee: []
created_date: '2026-09-24 11:22'
updated_date: '2026-09-24 13:02'
labels: []
dependencies: []
type: enhancement
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
'caldb --help' currently lists all 18 commands as one flat list (src/calibrationdb/cal_db_cli.py, Typer app defined at line 231). Typer's rich_markup_mode='rich' (already set, line 233) supports grouping commands into named panels via rich_help_panel="..." on each @app.command() decorator, rendered as separate sections in --help without changing any command behavior.

Proposed grouping (open to revision):
- Edit: add, update, rename, delete, restore
- Sync & Load: sync, review, load, export, status
- Inspect & Search: show, search, log, changes, diff, validate
- Snapshots: tag, tags, annotate
- Setup: install-hook

Related to task for possibly merging log/changes -- decide that first so the grouping reflects the final command set.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 caldb --help shows commands grouped into labeled sections instead of one flat list
- [x] #2 No command's name, options, or behavior changes -- this is help-output only
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added rich_help_panel='Edit'|'Sync & Load'|'Inspect & Search'|'Snapshots'|'Setup' to all 20 @app.command() decorators in src/calibrationdb/cal_db_cli.py, matching the proposed grouping. Verified with 'caldb --help' -- commands now render as 5 labeled panels instead of one flat list. No command names/options/behavior changed.
<!-- SECTION:NOTES:END -->
