import sqlite3
import hashlib
import json
import csv
import os
from datetime import datetime
from collections import namedtuple

# Define a named tuple for calibration parameters
CalibrationParameter = namedtuple('CalibrationParameter', [
    'name', 'value', 'comment', 'datatype', 'unit', 'size', 
    'min_val', 'max_val', 'description', 'aliases', 'mod_comment'
], defaults=(None, None, None, None, None, None, None, None, None, None, None))

class CalibrationDatabase:
    def __init__(self, db_file='data/calibration.db'):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file)
        self.create_table()

    def create_table(self):
        cur = self.conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS calibration (
                MID TEXT PRIMARY KEY,
                UID TEXT UNIQUE,
                Name TEXT,
                Value TEXT,
                COMMENT TEXT,
                DataType TEXT,
                Unit TEXT,
                Size TEXT,
                Min REAL,
                Max REAL,
                Description TEXT,
                ALIASES TEXT,
                ModifiedDateTime TEXT,
                ModificationComment TEXT,
                PreviousValues TEXT
            )
        ''')
        self.conn.commit()

    def add_parameter(self, prefix, param):
        if not param.name:
            print("Error: Parameter name is required.")
            return False
        uid = prefix + param.name
        mid = hashlib.md5(uid.encode()).hexdigest()
        cur = self.conn.cursor()
        
        # Check if name or aliases already exist
        cur.execute('''
            SELECT * FROM calibration 
            WHERE Name = ? OR ALIASES LIKE ? OR ALIASES LIKE ? OR ALIASES LIKE ?
        ''', (param.name, param.name, f'%;{param.name}', f'{param.name};%'))
        existing = cur.fetchone()

        if existing:
            print(f"Warning: Parameter with name '{param.name}' already exists in Name or ALIASES. Use update_parameter to modify.")
            return False
        
        try:
            cur.execute('''
                INSERT INTO calibration VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (mid, uid, param.name, param.value, param.comment, param.datatype, param.unit, 
                  param.size, param.min_val, param.max_val, param.description, param.aliases, 
                  datetime.now().isoformat(), param.mod_comment, ''))
            self.conn.commit()
            print(f"Added parameter {param.name} with MID {mid} and UID {uid}")
            return True
        except sqlite3.IntegrityError:
            print(f"Parameter with MID {mid} or UID {uid} already exists.")
            return False

    def update_parameter(self, param):
        if not param.name:
            print("Error: Parameter name is required.")
            return False

        cur = self.conn.cursor()
        
        # Check if name exists
        cur.execute('''
            SELECT * FROM calibration WHERE Name = ?
        ''', (param.name,))
        existing = cur.fetchone()

        if not existing:
            print(f"Parameter with name '{param.name}' not found in Names. Use add_parameter to create.")
            return False

        existing_mid, existing_uid, existing_name, old_value, old_comment, old_datatype, old_unit, old_size, old_min, old_max, old_desc, existing_aliases, _, old_mod_comment, old_prev_values = existing
        
        # Create modification comment for value change
        mod_comment = param.mod_comment
        if old_value != param.value and param.value is not None:
            changes = f"Value: {old_value} -> {param.value}"
            mod_comment = f"{param.mod_comment} | {changes}" if param.mod_comment else changes
        
        # Update previous values
        prev_values = old_value if not old_prev_values else f"{old_prev_values};{old_value}"

        # Use existing values for fields not being updated
        value = param.value if param.value is not None else old_value
        cur.execute('''
            UPDATE calibration 
            SET Value = ?, ModifiedDateTime = ?, ModificationComment = ?, PreviousValues = ?
            WHERE MID = ?
        ''', (value, datetime.now().isoformat(), mod_comment, prev_values, existing_mid))
        
        self.conn.commit()
        print(f"Updated parameter {param.name} with MID {existing_mid} and UID {existing_uid}")
        return True

    def rename_parameter(self, identifier, new_name, mod_comment=''):
        if not new_name:
            print("Error: New name is required.")
            return False
        cur = self.conn.cursor()
        cur.execute('''
            SELECT * FROM calibration WHERE MID = ? OR UID = ? OR Name = ?
        ''', (identifier, identifier, identifier))
        row = cur.fetchone()
        if row is None:
            print("Parameter not found.")
            return False
        mid, uid, old_name, value, comment, datatype, unit, size, min_val, max_val, description, aliases, _, _, _ = row
        if aliases:
            aliases += ';' + old_name
        else:
            aliases = old_name
        mod_comment = f"{mod_comment} | Name: {old_name} -> {new_name}" if mod_comment else f"Name: {old_name} -> {new_name}"
        cur.execute('''
            UPDATE calibration SET Name = ?, ALIASES = ?, ModifiedDateTime = ?, ModificationComment = ? WHERE MID = ?
        ''', (new_name, aliases, datetime.now().isoformat(), mod_comment, mid))
        self.conn.commit()
        print(f"Renamed parameter from {old_name} to {new_name}. UID {uid} and MID {mid} remain the same.")
        return True

    def load_from_csv(self, csv_file, prefix='cal-', delimiter=','):
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                min_val = float(row['Min']) if row.get('Min', '') else None
                max_val = float(row['Max']) if row.get('Max', '') else None
                param = CalibrationParameter(
                    name=row.get('Name', None),
                    value=row.get('Value', None),
                    comment=row.get('COMMENT', None),
                    datatype=row.get('DataType', None),
                    unit=row.get('Unit', None),
                    size=row.get('Size', None),
                    min_val=min_val,
                    max_val=max_val,
                    description=row.get('Description', None),
                    aliases=row.get('ALIASES', None),
                    mod_comment=row.get('ModificationComment', None)
                )
                self.add_parameter(prefix, param)

    def load_from_json(self, json_file, prefix='cal-'):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                data = [data]
            for item in data:
                min_val = float(item['Min']) if item.get('Min', '') else None
                max_val = float(item['Max']) if item.get('Max', '') else None
                param = CalibrationParameter(
                    name=item.get('Name', None),
                    value=item.get('Value', None),
                    comment=item.get('COMMENT', None),
                    datatype=item.get('DataType', None),
                    unit=item.get('Unit', None),
                    size=item.get('Size', None),
                    min_val=min_val,
                    max_val=max_val,
                    description=item.get('Description', None),
                    aliases=item.get('ALIASES', None),
                    mod_comment=item.get('ModificationComment', None)
                )
                self.add_parameter(prefix, param)

    def export_to_csv(self, csv_file, delimiter=','):
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM calibration')
        rows = cur.fetchall()
        columns = ['MID', 'UID', 'Name', 'Value', 'COMMENT', 'DataType', 'Unit', 'Size', 'Min', 'Max', 'Description', 'ALIASES', 'ModifiedDateTime', 'ModificationComment', 'PreviousValues']
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f"Database exported to {csv_file}")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    db = CalibrationDatabase('data/calibration.db')
    db.load_from_csv('data/example_cals.cal', prefix='cal-', delimiter=',')

    # Example adding a parameter
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

    # Example attempting to add a parameter with an existing alias
    param_alias = CalibrationParameter(
        name='ParamOld1',
        value='[10 90]',
        mod_comment='Trying to add with existing alias'
    )
    db.add_parameter('cal-', param_alias)  # Should warn and not add

    # Example updating a parameter
    param_update = CalibrationParameter(
        name='CalName2',
        value='[22 34]',
        mod_comment='Updated value for testing'
    )
    db.update_parameter(param_update)

    # Example renaming
    db.rename_parameter('ParamNew1', 'CalNewName1', 'Updated name for clarity')

    # Example exporting to CSV
    db.export_to_csv('data/calibration_export.csv')

    db.close()