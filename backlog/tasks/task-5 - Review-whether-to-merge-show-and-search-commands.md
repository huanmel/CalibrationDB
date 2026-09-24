---
id: TASK-5
title: Review whether to merge 'show' and 'search' commands
status: Done
assignee: []
created_date: '2026-09-24 13:21'
updated_date: '2026-09-24 13:27'
labels: []
dependencies: []
type: task
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
'show' (cal_db_cli.py:715-758) and 'search' (cal_db_cli.py:761-811) sit next to each other in the Inspect & Search help panel and share a lot of surface: same --compact/-c, --table/-T, --detail/-v flags, and both render through the identical _print_param_rows() helper. The divergence is in the filtering/query layer:

- 'show' takes only --name/-n (name or glob, cal_db_cli.py:718-720), defaults to showing ALL parameters when omitted, and uniquely supports --at TAG for point-in-time values (via get_parameters_at_tag).
- 'search' takes --name/-n plus --description/-D, --datatype/-t, --unit/-u, --source/-s (AND-ed), requires at least one filter or it errors (cal_db_cli.py:796-797), and has no --at / historical support.

Found a real inconsistency while reviewing, not just a style nit: the same flag --name/-n means different things in each command when given a bare (non-wildcard) string:
- show -> CalibrationDatabase.get_parameters() (cal_db_util.py:403-425): bare name is an EXACT match (`Name = ?`).
- search -> CalibrationDatabase.search_parameters()'s _add() (cal_db_util.py:427-463, see line ~444-447): bare name is a SUBSTRING match (`Name LIKE '%val%'`).

So 'caldb show -n FanSpdReqMax' and 'caldb search -n FanSpdReqMax' can return different result sets for the exact same flag and value (search would also match e.g. 'FanSpdReqMaxLow'). Wildcard patterns (containing * or ?) behave the same in both. This should be fixed regardless of whether the commands are merged.

Decide:
(a) Merge into one command -- 'show' gains search's extra filters (-D/-t/-u/-s), 'search' becomes a thin alias or is dropped. Needs reconciling "no filter = show all" (show's default) vs "no filter = error" (search's default).
(b) Keep separate -- 'show' stays the point-in-time/current-value lookup (its --at is a distinct, non-overlapping capability search doesn't have), 'search' stays the multi-field discovery query. Just fix the bare-name exact-vs-substring mismatch so --name/-n behaves identically wherever it appears.
(c) Something in between (e.g. show gets a --description/etc. passthrough without a full merge).

No code changes yet -- this task is to make the call, similar to how task-3 was scoped before the log/changes merge.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Decision recorded: merge show+search (with reasoning on default-filter and --at reconciliation), or keep separate, or partial merge
- [x] #2 Bare (non-wildcard) --name/-n matching is made consistent between show and search regardless of the merge decision (pick exact or substring, apply everywhere -n name matching is used)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Merged into 'show' (dropped 'search'):
- 'show' NAME is now an optional positional argument (matching the git-log style adopted for task-3's log merge), still name-or-glob, still defaults to all when omitted.
- 'show' gained search's -D/--description, -t/--datatype, -u/--unit, -s/--source filters, all AND-ed with NAME.
- CalibrationDatabase.search_parameters (cal_db_util.py) is now the single query path for show (replacing get_parameters for the CLI). Fixed the exact-vs-substring bug found during review: Name is now exact-match-or-glob (matching get_parameters()/log's semantics) instead of always substring; -D/-t/-u/-s remain substring-or-glob since fuzzy matching is what those fields need.
- Old requirement to error when zero filters given (search's behavior) was dropped -- 'show' with nothing given still means "show everything" (show's original behavior), which is a strict superset.
- --at TAG kept, but now explicitly rejects being combined with -D/-t/-u/-s (typer.BadParameter) since get_parameters_at_tag only supports name-pattern filtering; combining --at with NAME still works as before.
Verified against example/example.db: show (all), show NAME (exact), show "glob*", show -D/-t combo, show NAME --at TAG, show NAME --at TAG combined with -D (correctly rejected), and confirmed 'caldb search' now errors with 'No such command'. Updated README.md (merged show/search sections) and ROADMAP.md.
<!-- SECTION:NOTES:END -->
