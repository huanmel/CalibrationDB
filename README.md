# cal_db
calibration parameters database util


### CLI Usage Examples :
- Add a parameter:

  ```bash
  python cal_db_cli.py --db data/calibration.db add --prefix cal- --name ParamNew1 --value "[0 80]" --datatype uint8 --unit per --size 2 --description "param description" --aliases "ParamOld1;ParamOld2" --mod-comment "Initial addition"
  ```
  
- Update a parameter (only name and value):
  ```bash
  python cal_db_cli.py --db data/calibration.db update --name ParamNew1 --value "[10 90]" --mod-comment "Updated value for testing"
  ```
- Rename a parameter:
  ```bash
  python cal_db_cli.py --db data/calibration.db rename --identifier ParamNew1 --new-name CalNewName1 --mod-comment "Updated name for clarity"
  ```
- Load from CSV:
  ```bash
  python cal_db_cli.py --db data/calibration.db load --file data/example_cals.cal --type csv
  ```
- Export to CSV:
  ```bash
  python cal_db_cli.py --db data/calibration.db export --file data/calibration_export.csv
  ```

### Notes:
- The `cal_db_cli.py` file imports `CalibrationDatabase` and `CalibrationParameter` from `cal_db_util.py`, so both files must be in the same directory (e.g., `src/`).
- The `update_parameter` method now only updates the value (and name for renaming), preserving other fields like `DataType`, `Unit`, etc., from the existing record.
- The `PreviousValues` column and automatic modification comments (e.g., "Value: old -> new") are retained from the previous version.
- The artifact ID for `cal_db_util.py` is kept the same, and a new artifact ID is assigned to `cal_db_cli.py`.
