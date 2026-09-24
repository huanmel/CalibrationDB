---
id: TASK-2
title: Audit inconsistent short-flag reuse across CLI commands
status: To Do
assignee: []
created_date: '2026-09-24 11:22'
updated_date: '2026-09-24 13:17'
labels: []
dependencies: []
type: chore
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Scanned all @app.command() option definitions in src/calibrationdb/cal_db_cli.py. Several single-letter short flags mean different things depending on the command, which is confusing muscle memory across the CLI:

-n : --name (add, update, delete, show, search, restore, tag) vs --count (changes, annotate)
-c : --comment (add, delete, sync, restore) vs --compact (show, search, changes)
-s : --source (search) vs --since (changes, annotate)
-t : --datatype (search) vs --type/change-type (changes, annotate)
-u : --unit (add, search) vs --until (annotate)
-v : --value (add, update) vs --detail (show, search, log, changes)
-m : --mod-comment (add, update, rename) vs --message (tag, annotate) -- same concept, different option name, minor

Consistent ones worth keeping as the pattern: -d/--db (global), -p/--prefix, -T/--table, -f/--file.

Decide on a canonical mapping (e.g. -n always means name-filter; move 'count' to --count only or a different letter like -k/-N) and apply it across all commands. This blocks adding a wildcard name filter to 'changes' cleanly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Written decision on which short flag maps to which long option, applied consistently across all commands
- [ ] #2 Breaking changes to existing short flags (e.g. changes -n today meaning --count) are called out, since they affect muscle memory / scripts already using this CLI
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Update: the -n collision between 'changes' --count and other commands' --name is resolved by task-3's merge -- 'log' now takes NAME as an optional positional argument (git log style), so -n is free to always mean --count everywhere. Remaining collisions to decide: -c (comment vs compact), -s (source vs since), -t (datatype vs change-type), -v (value vs detail), -m (mod-comment vs message, minor).
<!-- SECTION:NOTES:END -->
