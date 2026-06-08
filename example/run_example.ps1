# caldb example workflow
# Run from the repo root:  .\example\run_example.ps1
#
# Requires caldb to be installed (pip install .) in an environment whose
# Scripts folder is on PATH.  If using Miniforge/conda, either activate the
# base env first, or uncomment the line below to add Scripts to PATH temporarily:
$env:PATH = "$env:USERPROFILE\miniforge3\Scripts;$env:PATH"

$db   = "example\example.db"
$csv  = "example\example_cal.csv"
$csv2 = "example\example_cal_v2.csv"

# Clean up from previous runs
Remove-Item -Force $db -ErrorAction SilentlyContinue

Write-Host "`n=== 1. Initial sync from CSV ===" -ForegroundColor Cyan
caldb -d $db sync -f $csv -c "initial import"

Write-Host "`n=== 2. History for a single parameter ===" -ForegroundColor Cyan
caldb -d $db log -n TempCtlSetPnt

Write-Host "`n=== 3. Simulate editing the CSV (create a modified copy) ===" -ForegroundColor Cyan
# Bump TempCtlSetPnt from 22.5 -> 24.0 and FanSpdReqMax from 100 -> 90
(Get-Content $csv) `
    -replace '^TempCtlSetPnt,22\.5,', 'TempCtlSetPnt,24.0,' `
    -replace '^FanSpdReqMax,100,',    'FanSpdReqMax,90,' |
    Set-Content $csv2
Write-Host "  Modified copy saved to $csv2"

Write-Host "`n=== 4. Sync the modified CSV — should detect 2 changed ===" -ForegroundColor Cyan
caldb -d $db sync -f $csv2 -c "cold weather tuning"

Write-Host "`n=== 5. Full history for TempCtlSetPnt ===" -ForegroundColor Cyan
caldb -d $db log -n TempCtlSetPnt

Write-Host "`n=== 6. Add a new parameter via CLI ===" -ForegroundColor Cyan
caldb -d $db add -n FanSpdRateLim -v 10 --datatype uint8 --unit "per/s" --size 1 `
    -m "rate limiter added in sprint 5"

Write-Host "`n=== 7. Update a parameter via CLI ===" -ForegroundColor Cyan
caldb -d $db update -n PmpSpdMin -v 600 -m "raised idle speed to avoid stall"

Write-Host "`n=== 8. Log for PmpSpdMin ===" -ForegroundColor Cyan
caldb -d $db log -n PmpSpdMin

Write-Host "`n=== 9. Soft-delete a parameter ===" -ForegroundColor Cyan
caldb -d $db delete -n FaultRecovTout -c "merged into FaultTout"

Write-Host "`n=== 10. Export DB to CSV ===" -ForegroundColor Cyan
caldb -d $db export -f example\export.csv
Write-Host "  Rows in export:"
(Get-Content example\export.csv).Count - 1   # subtract header

# Clean up temp file
Remove-Item -Force $csv2 -ErrorAction SilentlyContinue
