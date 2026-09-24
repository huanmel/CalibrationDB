---
id: TASK-4
title: Add wildcard support to 'caldb log's NAME filter
status: Done
assignee: []
created_date: '2026-09-24 11:22'
updated_date: '2026-09-24 13:31'
labels: []
dependencies: []
type: enhancement
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Superseded by task-3's merge of 'log'/'changes': 'caldb log' (cal_db_cli.py) now takes an optional positional NAME argument, exact match only -- e.g. 'caldb log TempCtlSetPnt'. 'caldb changes' no longer exists.

Remaining scope: upgrade that NAME argument to accept glob patterns (* and ?), matching the syntax already used by 'caldb search', 'caldb show', and 'caldb diff' (fnmatch-based). Currently CalibrationDatabase.get_recent_changes (cal_db_util.py) does an exact 'Name = ?' match when name is given; a glob pattern would need fnmatch filtering in Python (fetch broader/all matching rows, then filter), similar to how show/search already do it, since fnmatch has no direct SQL equivalent.

No more flag collision to resolve -- NAME is positional, -n is free and always means --count (git log convention), consistent with the rest of the CLI's -n usage elsewhere.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Filter is applied consistently whether or not --by-tag is used
- [x] #2 caldb log accepts a glob pattern as NAME (*, ?), matching the same syntax as search/show/diff
- [x] #3 caldb log NAME (exact, no wildcard) continues to behave exactly as it does today
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Added glob support to CalibrationDatabase.get_recent_changes's name= param (cal_db_util.py): when name contains * or ?, it's converted to a SQL LIKE pattern (replace('*','%').replace('?','_')) same as get_parameters()/search_parameters(); otherwise still an exact 'Name = ?' match. Done directly in SQL (not fnmatch-after-fetch) so the -n/--count LIMIT still applies correctly per query.
Updated 'caldb log's NAME argument help text, docstring examples, and README to drop the old 'exact match only' caveat.
Verified against example/example.db: 'caldb log "FanSpd*" -n 0' returns all 6 history entries across FanSpdMapX/Y, FanSpdRateLim, FanSpdReqMax, FanSpdReqMin; 'caldb log TempCtlSetPnt' (exact) unaffected; 'caldb log "NoSuch*"' handled gracefully with the existing no-match message.
<!-- SECTION:NOTES:END -->
