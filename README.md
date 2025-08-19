# CalibrationDB

CalibrationDB is a Python package for managing calibration parameters in a SQLite database, with support for importing/exporting data in CSV and JSON formats. It provides a robust way to store, update, and track calibration parameters with unique identifiers (MID and UID), aliases, and modification history. The package includes a programmatic API (`cal_db_util.py`) and a command-line interface (`cal_db_cli.py`).

## Features

- **SQLite Database Storage**: Stores calibration parameters in a SQLite database with fields for MID, UID, Name, Value, Comment, DataType, Unit, Size, Min, Max, Description, Aliases, ModifiedDateTime, ModificationComment, and PreviousValues.
- **Unique Identifiers**:
  - **MID**: A unique MD5 hash generated from the UID.
  - **UID**: A combination of a user-defined prefix and the parameter name.
- **Add Parameters**: Add new parameters with validation to prevent duplicates in Name or Aliases.
- **Update Parameters**: Update only the value of an existing parameter, preserving other attributes, with automatic tracking of previous values and change comments.
- **Rename Parameters**: Rename parameters while preserving MID and UID, storing the old name in Aliases.
- **Modification Tracking**: Automatically records modification timestamps and generates comments for changes (e.g., "Value: old -> new" or "Name: old -> new").
- **Previous Values**: Stores a history of previous values for each parameter in a semicolon-separated list.
- **Import/Export**:
  - Import parameters from CSV or JSON files.
  - Export the entire database to CSV with all fields.
- **Command-Line Interface**: A CLI (`cal_db_cli.py`) for adding, updating, renaming, loading, and exporting parameters.
- **Flexible Data Handling**: Supports optional fields (e.g., Min, Max can be NULL) and handles missing values gracefully.

## Installation

### Prerequisites
- Python 3.6 or higher
- No external dependencies required (uses standard library modules: `sqlite3`, `hashlib`, `json`, `csv`, `os`, `datetime`, `argparse`, `collections`)

### Install via pip
1. **Clone the Repository** (optional, for development):
   ```bash
   git clone https://github.com/huanmel/CalibrationDB.git
   cd CalibrationDB
   pip install .
   ```
   This installs the package locally.

2. **Install from GitHub** (direct installation):
   ```bash
   pip install git+https://github.com/huanmel/CalibrationDB.git
   ```

3. **Create Data Directory**:
   The package uses a `data` directory for the database and input/output files. Create it in your working directory:
   ```bash
   mkdir data
   ```

### Verify Installation
After installation, the `calibrationdb` CLI command should be available:
```bash
calibrationdb --help
```

## Usage

### Programmatic Usage
The `calibrationdb` package provides the `CalibrationDatabase` class for programmatic interaction. Example:

```python
from calibrationdb import CalibrationDatabase, CalibrationParameter

db = CalibrationDatabase('data/calibration.db')

# Add a parameter
param = CalibrationParameter(
    name='ParamNew1',
    value='[0 80]',
    datatype='uint8',
    unit='per',
    size='2',
    description='param description for testing',
    aliases='ParamOld1;ParamOld2',
    mod_comment='Initial parameter addition'
)
db.add_parameter('cal-', param)

# Update a parameter (only value)
param_update = CalibrationParameter(
    name='ParamNew1',
    value='[10 90]',
    mod_comment='Updated value for testing'
)
db.update_parameter(param_update)

# Rename a parameter
db.rename_parameter('ParamNew1', 'CalNewName1', 'Updated name for clarity')

# Export to CSV
db.export_to_csv('data/calibration_export.csv')

db.close()
```

### Command-Line Interface
The `calibrationdb` command provides a CLI for managing the database. Run with `--help` for details:

```bash
calibrationdb --help
```

#### CLI Commands
- **Add a parameter**:
  ```bash
  calibrationdb --db data/calibration.db add --prefix cal- --name ParamNew1 --value "[0 80]" --datatype uint8 --unit per --size 2 --description "param description" --aliases "ParamOld1;ParamOld2" --mod-comment "Initial addition"
  ```
- **Update a parameter** (updates only value):
  ```bash
  calibrationdb --db data/calibration.db update  --name ParamNew1 --value "[10 90]" --mod-comment "Updated value for testing"
  ```
- **Rename a parameter**:
  ```bash
  calibrationdb --db data/calibration.db rename --identifier ParamNew1 --new-name CalNewName1 --mod-comment "Updated name for clarity"
  ```
- **Load from CSV**:
  ```bash
  calibrationdb --db data/calibration.db load --file data/example_cals.cal --type csv
  ```
- **Export to CSV**:
  ```bash
  calibrationdb --db data/calibration.db export --file data/calibration_export.csv
  ```

### Input File Formats
- **CSV**: Expected columns: `MID`, `UID`, `Name`, `Value`, `COMMENT`, `DataType`, `Unit`, `Size`, `Min`, `Max`, `Description`, `ALIASES`, `ModifiedDateTime`, `ModificationComment`, `PreviousValues`. Only `Name` is required; others are optional.
- **JSON**: Array of objects with the same fields as CSV. Example:
  ```json
  [
      {
          "Name": "ParamNew1",
          "Value": "[0 80]",
          "DataType": "uint8",
          "Unit": "per",
          "Size": "2",
          "Description": "param description for testing",
          "ALIASES": "ParamOld1;ParamOld2",
          "ModificationComment": "Initial addition"
      }
  ]
  ```

## Project Structure
```
CalibrationDB/
├── calibrationdb/
│   ├── __init__.py
│   ├── cal_db_util.py      # Core database logic
│   ├── cal_db_cli.py       # Command-line interface
├── data/
│   ├── calibration.db      # SQLite database (created automatically, not in repo)
│   ├── example_cals.cal    # Input CSV file (optional, not in repo)
│   ├── calibration_export.csv  # Output CSV file (not in repo)
├── pyproject.toml
├── MANIFEST.in
├── LICENSE
├── README.md
├── .gitignore
```

## Notes
- The database is stored in `data/calibration.db` by default.
- The `PreviousValues` field tracks the history of parameter values in a semicolon-separated list.
- Modification comments automatically include changes (e.g., "Value: old -> new" or "Name: old -> new").
- The `add_parameter` method prevents adding parameters with names that already exist in `Name` or `ALIASES`.
- The `update_parameter` method only modifies the `Value` field, preserving other attributes.

## Contributing
Contributions are welcome! Please submit issues or pull requests on GitHub.

## License
MIT License