"""Regression tests for calibration vectors longer than 10 values (commit 92de356).

Before that commit, multi-column CSVs were hardcoded to Value_1..Value_10: reads
silently dropped elements 11+ and write-back truncated to 10. These tests pin the
fixed behaviour: _value_cols() reads however many Value_N columns the CSV header
actually has, and write-back grows the header instead of truncating.
"""
import csv

import pytest

from calibrationdb.cal_db_util import CalibrationParameter, _load_csv_params, _split_to_value_cols


def test_multicol_read_all_values(multicol_csv_writer):
    """AC1: a 16-value calibration is read with all values (columns taken from the header)."""
    values = [str(i) for i in range(1, 17)]
    path, _ = multicol_csv_writer('cal.csv', 16, [
        {'Name': 'Mask16', 'Value': ' '.join(values)},
    ])

    params = _load_csv_params(str(path))

    assert params['Mask16'].value == ' '.join(values)


def test_writeback_extends_columns_for_longer_vector(db, multicol_csv_writer):
    """AC2: write-back into a 10-column CSV adds Value_11..Value_16 after the last
    value column, before the metadata columns (COMMENT etc.)."""
    path, fieldnames = multicol_csv_writer('cal.csv', 10, [
        {'Name': 'FanMap', 'Value': ' '.join(str(i) for i in range(1, 11))},
    ])
    db.sync_from_csv(str(path), prefix='CAL-')

    new_value = ' '.join(str(i) for i in range(1, 17))
    db.update_parameter(CalibrationParameter(name='FanMap', value=new_value))

    diff = db.compute_db_to_csv_diff(str(path))
    db.write_back_to_csv(str(path), diff)

    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        new_fieldnames = reader.fieldnames
        row = next(reader)

    expected_value_cols = [f'Value_{i}' for i in range(1, 17)]
    assert new_fieldnames[1:17] == expected_value_cols
    assert new_fieldnames[17] == 'COMMENT'
    assert [row[c] for c in expected_value_cols] == [str(i) for i in range(1, 17)]


def test_writeback_unchanged_header_when_values_fit(db, multicol_csv_writer):
    """AC4: an existing 10-column CSV gives the same result as before (no extra
    columns written) when every value still fits in Value_1..Value_10."""
    path, fieldnames = multicol_csv_writer('cal.csv', 10, [
        {'Name': 'FanMap', 'Value': '1 2 3 4 5'},
    ])
    db.sync_from_csv(str(path), prefix='CAL-')
    db.update_parameter(CalibrationParameter(name='FanMap', value='9 9 9 9 9'))

    diff = db.compute_db_to_csv_diff(str(path))
    db.write_back_to_csv(str(path), diff)

    with open(path, newline='', encoding='utf-8') as f:
        new_fieldnames = csv.DictReader(f).fieldnames

    assert new_fieldnames == fieldnames


def test_split_to_value_cols_raises_instead_of_truncating():
    """AC3: Size larger than the available value columns raises an error,
    no silent truncation."""
    row = {}
    value_cols = ['Value_1', 'Value_2', 'Value_3']

    with pytest.raises(ValueError, match=r'4 values but the CSV has only Value_1\.\.Value_3'):
        _split_to_value_cols(row, value_cols, '1 2 3 4', 'SomeParam')

    # nothing should have been written, not even a partial/truncated set
    assert row == {}


def test_sync_detects_change_deep_in_long_vector(db, multicol_csv_writer):
    """AC5: a change only in value 14 (of 16) is detected by sync and recorded
    in the history."""
    original = [str(i) for i in range(1, 17)]
    path, _ = multicol_csv_writer('cal.csv', 16, [
        {'Name': 'Mask16', 'Value': ' '.join(original)},
    ])
    added, changed, deleted, meta = db.sync_from_csv(str(path), prefix='CAL-')
    assert added == ['Mask16']

    changed_values = list(original)
    changed_values[13] = '999'  # element 14, 1-indexed
    multicol_csv_writer('cal.csv', 16, [
        {'Name': 'Mask16', 'Value': ' '.join(changed_values)},
    ])

    added2, changed2, deleted2, meta2 = db.sync_from_csv(str(path), prefix='CAL-')
    assert added2 == []
    assert deleted2 == []
    assert changed2 == ['Mask16']

    entries = db.get_parameter_log('Mask16', limit=1)
    assert entries[0]['ChangeType'] == 'update'
    assert entries[0]['OldValue'] == ' '.join(original)
    assert entries[0]['NewValue'] == ' '.join(changed_values)
