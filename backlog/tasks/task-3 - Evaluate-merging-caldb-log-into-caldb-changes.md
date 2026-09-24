---
id: TASK-3
title: Evaluate merging 'caldb log' into 'caldb changes'
status: Done
assignee: []
created_date: '2026-09-24 11:22'
updated_date: '2026-09-24 13:17'
labels: []
dependencies: []
type: task
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
'caldb log NAME' (cal_db_cli.py:988-1030) and 'caldb changes' (cal_db_cli.py:1387-1546) overlap significantly:
- Both walk calibration_history and render it with the same table helper (_print_changes_table / _format_change_compact).
- 'log' takes a required positional NAME (exact match only, via db.get_parameter_log), shows only that parameter's history, with --limit/-l.
- 'changes' shows history across all parameters, filterable by --type/-t and --since/-s, with --compact/--table/--detail views and tag markers (--by-tag).

Once 'changes' gains a glob-capable --name filter (see other task), 'caldb changes -n TempCtlSetPnt' would produce nearly the same output as 'caldb log TempCtlSetPnt', minus tag markers, which 'changes' already has anyway.

Decide: 
(a) drop 'log' and route its behavior through 'changes' internals (keep 'log NAME' as a thin backward-compatible alias for 'changes -n NAME --type ...'), or
(b) keep both as separate commands but share more of the underlying query path, or
(c) leave as-is if the exact-name-only + positional-arg ergonomics of 'log' are worth keeping separate from 'changes' filter syntax.

No code changes yet -- this task is to make the call before touching either command.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Decision recorded: merge log into changes (with/without a compat alias), or keep both, with reasoning
- [x] #2 If merging: confirm no loss of functionality (limit=0/all, --detail view, tag markers) for existing 'log' users
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Merged 'log' and 'changes' into a single command 'log', modeled on 'git log [<path>] [options]':
- name is now an optional positional argument (typer.Argument(None, ...)) instead of log's old required positional. Omit it -> changes across all parameters (old 'changes' behavior). Pass it -> history for just that parameter, exact match only (wildcards deferred, see task-4).
- -n/--count now always means count (git's own convention), never name -- this also resolves the -n collision noted in task-2 for this pair specifically.
- CalibrationDatabase.get_recent_changes (cal_db_util.py) gained an optional name= kwarg (exact SQL match), reused by both code paths; old get_parameter_log is now only used internally by 'restore' (cal_db_cli.py:964) and untouched.
- Fixed a latent bug found during review: the old 'log' claimed '--limit 0 = all' but get_parameter_log did LIMIT 0 (SQLite), returning zero rows. The merged command always goes through get_recent_changes, which handles 0=all correctly -- verified 'caldb log NAME -n 0' now returns full history.
- 'caldb changes' no longer exists (dropped per decision, not aliased). Updated all references in cal_db_cli.py docstrings/comments and README.md/ROADMAP.md.
Verified manually against example/example.db: log (all), log NAME (table + header), log NAME -n 0, log -n 0 -v (count), log NoSuchParam, log -t update -c -v, log --by-tag, and confirmed 'caldb changes' now errors with 'No such command'.
<!-- SECTION:NOTES:END -->
