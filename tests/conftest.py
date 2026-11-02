import csv

import pytest

from calibrationdb.cal_db_util import CalibrationDatabase

# Metadata columns that follow the Value_N columns in a real multi-column CSV
# (see example/example_cal.csv): Name, Value_1..Value_N, then these.
MULTICOL_META_COLS = [
    'COMMENT', 'DataType', 'Unit', 'Size', 'Min', 'Max', 'Description', 'Who', 'Users', 'Source',
]


@pytest.fixture
def db(tmp_path):
    database = CalibrationDatabase(str(tmp_path / 'test.db'))
    yield database
    database.close()


@pytest.fixture
def multicol_csv_writer(tmp_path):
    """Returns a function that (re)writes a multi-column calibration CSV.

    write(filename, n_cols, rows) -> (path, fieldnames)
      n_cols:   number of Value_N columns in the header
      rows:     [{'Name': str, 'Value': 'space separated string', **metadata}, ...]
    """
    def _write(filename, n_cols, rows):
        path = tmp_path / filename
        value_cols = [f'Value_{i}' for i in range(1, n_cols + 1)]
        fieldnames = ['Name'] + value_cols + MULTICOL_META_COLS
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                out = {c: '' for c in fieldnames}
                out['Name'] = r['Name']
                parts = (r.get('Value') or '').split()
                for col, part in zip(value_cols, parts):
                    out[col] = part
                for k in MULTICOL_META_COLS:
                    if k in r:
                        out[k] = r[k]
                writer.writerow(out)
        return path, fieldnames
    return _write
