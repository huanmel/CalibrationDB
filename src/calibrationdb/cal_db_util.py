import sqlite3
import hashlib
import json
import csv
import fnmatch
from datetime import datetime
from collections import namedtuple

CalibrationParameter = namedtuple('CalibrationParameter', [
    'name', 'value', 'comment', 'datatype', 'unit', 'size',
    'min_val', 'max_val', 'description', 'aliases', 'mod_comment',
    'who', 'users', 'source'
], defaults=(None,) * 14)

_VALUE_COLS = [f'Value_{i}' for i in range(1, 11)]


def _canonicalise_value(v):
    """Normalise array value to a canonical space-separated form.

    Handles both bracket notation ([0, 1, 2] or [0 1 2]) and plain
    space/comma-separated strings so that both CSV formats compare equal.
    """
    if v is None:
        return ''
    s = str(v).strip().strip('[]')   # remove surrounding brackets
    s = s.replace(',', ' ')          # commas → spaces
    return ' '.join(s.split())       # collapse whitespace


def _normalise_value(v):
    """Alias used for comparisons — same as _canonicalise_value."""
    return _canonicalise_value(v)


_INT_TYPES = {
    'boolean', 'bool',
    'uint8', 'uint16', 'uint32', 'uint64',
    'int8',  'int16',  'int32',  'int64',
}
_NUMERIC_TYPES = _INT_TYPES | {'single', 'double', 'float', 'float32', 'float64'}

# Hard limits imposed by the data type itself (independent of Min/Max fields)
_TYPE_RANGES = {
    'boolean': (0, 1),    'bool':   (0, 1),
    'uint8':   (0, 255),  'uint16': (0, 65535),
    'uint32':  (0, 4294967295),
    'uint64':  (0, 18446744073709551615),
    'int8':    (-128, 127),         'int16': (-32768, 32767),
    'int32':   (-2147483648, 2147483647),
    'int64':   (-9223372036854775808, 9223372036854775807),
}


def _validate_value(value, min_val=None, max_val=None, datatype=None, size=None):
    """Check value against constraints. Returns list of warning strings."""
    issues = []
    if not value:
        return issues
    elements = _canonicalise_value(value).split()

    if size:
        try:
            if len(elements) != int(size):
                issues.append(f"size: expected {int(size)} element(s), got {len(elements)}")
        except (ValueError, TypeError):
            pass

    dt = (datatype or '').lower().strip()
    is_int     = dt in _INT_TYPES
    is_numeric = dt in _NUMERIC_TYPES
    type_range = _TYPE_RANGES.get(dt)      # (hard_min, hard_max) or None
    is_bool    = dt in ('boolean', 'bool')

    for elem in elements:
        try:
            num = float(elem)
        except (ValueError, TypeError):
            if is_numeric:
                issues.append(f"non-numeric value '{elem}' for type {datatype}")
            continue

        # Fractional value in an integer type
        if is_int and num != int(num):
            issues.append(f"non-integer {num} for type {datatype}")
            continue  # skip range checks — value is already malformed

        # Boolean: only 0 or 1 allowed
        if is_bool and int(num) not in (0, 1):
            issues.append(f"{int(num)} is not a valid boolean (must be 0 or 1)")

        # Type-inherent hard limits (e.g. uint8 must be 0-255)
        elif type_range is not None:
            tmin, tmax = type_range
            if num < tmin:
                issues.append(f"{elem} below {datatype} minimum ({tmin})")
            elif num > tmax:
                issues.append(f"{elem} exceeds {datatype} maximum ({tmax})")

        # Explicit parameter Min/Max (may be narrower than the type range)
        if min_val is not None and num < float(min_val):
            issues.append(f"{elem} < Min ({min_val})")
        if max_val is not None and num > float(max_val):
            issues.append(f"{elem} > Max ({max_val})")

    return issues


def _format_meta_diff(p, db_row):
    """Return a human-readable summary of which metadata fields changed."""
    def _s(v): return '' if v is None else str(v)
    checks = [
        ('DataType',    _s(p.datatype),    _s(db_row.get('DataType'))),
        ('Unit',        _s(p.unit),        _s(db_row.get('Unit'))),
        ('Size',        _s(p.size),        _s(db_row.get('Size'))),
        ('Min',         _s(p.min_val),     _s(db_row.get('Min'))),
        ('Max',         _s(p.max_val),     _s(db_row.get('Max'))),
        ('Description', _s(p.description), _s(db_row.get('Description'))),
        ('Who',         _s(p.who),         _s(db_row.get('Who'))),
        ('Source',      _s(p.source),      _s(db_row.get('Source'))),
    ]
    return ' | '.join(f"{lbl}: {old} -> {new}"
                      for lbl, new, old in checks if new != old)


def _parse_multicol_row(row):
    """Parse a row from the multi-column CSV format (Value_1 .. Value_10)."""
    parts = [row.get(c, '').strip() for c in _VALUE_COLS]
    value = ' '.join(p for p in parts if p) or None
    min_val = float(row['Min']) if row.get('Min', '').strip() else None
    max_val = float(row['Max']) if row.get('Max', '').strip() else None
    param = CalibrationParameter(
        name=row.get('Name', '').strip() or None,
        value=value,
        comment=row.get('COMMENT', '').strip() or None,
        datatype=row.get('DataType', '').strip() or None,
        unit=row.get('Unit', '').strip() or None,
        size=row.get('Size', '').strip() or None,
        min_val=min_val,
        max_val=max_val,
        description=row.get('Description', '').strip() or None,
        aliases=None,
        mod_comment=None,
        who=row.get('Who', '').strip() or None,
        users=row.get('Users', '').strip() or None,
        source=row.get('Source', '').strip() or None,
    )
    return param


def _parse_standard_row(row):
    """Parse a row from the original single-Value-column CSV format."""
    min_val = float(row['Min']) if row.get('Min', '').strip() else None
    max_val = float(row['Max']) if row.get('Max', '').strip() else None
    raw_value = row.get('Value', '').strip()
    return CalibrationParameter(
        name=row.get('Name', '').strip() or None,
        value=_canonicalise_value(raw_value) or None,
        comment=row.get('COMMENT', '').strip() or None,
        datatype=row.get('DataType', '').strip() or None,
        unit=row.get('Unit', '').strip() or None,
        size=row.get('Size', '').strip() or None,
        min_val=min_val,
        max_val=max_val,
        description=row.get('Description', '').strip() or None,
        aliases=row.get('ALIASES', '').strip() or None,
        mod_comment=row.get('ModificationComment', '').strip() or None,
        who=None,
        users=None,
        source=None,
    )


class CalibrationDatabase:
    def __init__(self, db_file='data/calibration.db', test_mode=False):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file)
        self.create_table()
        self.test_mode = test_mode
        if test_mode:
            self.conn.isolation_level = None

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
        # Add columns that may not exist in older databases
        for col_def in [
            'Deleted INTEGER DEFAULT 0',
            'Who TEXT',
            'Users TEXT',
            'Source TEXT',
        ]:
            try:
                cur.execute(f'ALTER TABLE calibration ADD COLUMN {col_def}')
            except sqlite3.OperationalError:
                pass  # column already exists

        cur.execute('''
            CREATE TABLE IF NOT EXISTS calibration_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                Name           TEXT,
                ChangeType     TEXT,
                OldValue       TEXT,
                NewValue       TEXT,
                OldComment     TEXT,
                NewComment     TEXT,
                ChangeDateTime TEXT,
                SyncComment    TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS _caldb_meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS _caldb_tags (
                name          TEXT PRIMARY KEY,
                ChangeDateTime TEXT,
                comment        TEXT
            )
        ''')
        self.conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_db_changed(self, cur):
        """Record that the DB was modified via CLI since last sync."""
        cur.execute(
            "INSERT OR REPLACE INTO _caldb_meta (key, value) VALUES ('db_changed', ?)",
            (datetime.now().isoformat(),),
        )

    def _insert_history(self, cur, name, change_type,
                        old_value=None, new_value=None,
                        old_comment=None, new_comment=None,
                        sync_comment=None):
        cur.execute('''
            INSERT INTO calibration_history
                (Name, ChangeType, OldValue, NewValue, OldComment, NewComment, ChangeDateTime, SyncComment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, change_type, old_value, new_value,
              old_comment, new_comment,
              datetime.now().isoformat(), sync_comment))

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_parameter(self, name, to_value, to_comment=None, restore_comment=''):
        """Set a parameter's value to to_value and record a 'restore' history entry.

        to_comment  - the comment to store on the parameter row; if None the
                      existing comment is kept unchanged.
        Returns True if the value was changed, False if it was already equal.
        """
        cur = self.conn.cursor()
        cur.execute(
            'SELECT Value, COMMENT FROM calibration'
            ' WHERE Name = ? AND (Deleted = 0 OR Deleted IS NULL)',
            (name,),
        )
        row = cur.fetchone()
        if not row:
            print(f"  '{name}': not found or deleted.")
            return False
        old_value, old_comment = row
        if _normalise_value(old_value) == _normalise_value(to_value):
            return False
        new_comment = to_comment if to_comment is not None else old_comment
        self._insert_history(cur, name, 'restore',
                             old_value=old_value, new_value=to_value,
                             old_comment=old_comment, new_comment=new_comment,
                             sync_comment=restore_comment)
        cur.execute('''
            UPDATE calibration
            SET Value = ?, COMMENT = ?, ModifiedDateTime = ?, ModificationComment = ?
            WHERE Name = ?
        ''', (to_value, new_comment, datetime.now().isoformat(), restore_comment, name))
        self._set_db_changed(cur)
        self.conn.commit()
        return True

    def restore_to_previous(self, name, restore_comment=''):
        """Restore a parameter to the value it had before its last change.

        Returns True if restored, False if no previous value exists.
        """
        cur = self.conn.cursor()
        cur.execute('''
            SELECT OldValue, OldComment FROM calibration_history
            WHERE Name = ? AND OldValue IS NOT NULL
            ORDER BY id DESC LIMIT 1
        ''', (name,))
        row = cur.fetchone()
        if not row:
            print(f"  '{name}': no previous value found.")
            return False
        return self.restore_parameter(name, row[0], row[1], restore_comment)

    def compute_restore_diff(self, tag_name, pattern=None):
        """Return parameters that differ between current DB state and a tag.

        Returns (tag_time_str, diff_list) or (None, None) if the tag doesn't exist.
        diff_list entries: {'name', 'current', 'target', 'target_comment'}
        Parameters deleted since the tag are skipped.
        """
        tag_time, tag_rows = self.get_parameters_at_tag(tag_name, pattern=pattern)
        if tag_time is None or tag_rows is None:
            return None, None
        current = {r['Name']: r for r in self.get_parameters(pattern)}
        diff = []
        for row in tag_rows:
            name = row['Name']
            if name not in current:
                continue  # deleted since the tag; skip
            if _normalise_value(current[name]['Value']) != _normalise_value(row['Value']):
                diff.append({
                    'name': name,
                    'current': current[name]['Value'],
                    'target': row['Value'],
                    'target_comment': row.get('COMMENT'),
                })
        return tag_time, diff

    def validate_parameters(self, pattern=None):
        """Validate active parameters against their Min/Max/DataType/Size constraints.

        Returns list of {name, value, warnings} for parameters with violations.
        """
        results = []
        for r in self.get_parameters(pattern):
            issues = _validate_value(
                r['Value'],
                min_val=r.get('Min'),
                max_val=r.get('Max'),
                datatype=r.get('DataType'),
                size=r.get('Size'),
            )
            if issues:
                results.append({'name': r['Name'], 'value': r['Value'], 'warnings': issues})
        return results

    def get_parameters(self, pattern=None):
        """Return a list of active parameter row dicts.

        pattern  None  -> all parameters
                 str   -> exact name match, or glob-style wildcard (* -> SQL %)
        """
        cur = self.conn.cursor()
        base = '''
            SELECT MID, UID, Name, Value, COMMENT, DataType, Unit, Size,
                   Min, Max, Description, ALIASES, ModifiedDateTime,
                   ModificationComment, Who, Users, Source
            FROM calibration
            WHERE (Deleted = 0 OR Deleted IS NULL)
        '''
        if pattern is None:
            cur.execute(base + ' ORDER BY Name')
        elif '*' in pattern or '?' in pattern:
            sql_pattern = pattern.replace('*', '%').replace('?', '_')
            cur.execute(base + ' AND Name LIKE ? ORDER BY Name', (sql_pattern,))
        else:
            cur.execute(base + ' AND Name = ?', (pattern,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def search_parameters(self, name=None, description=None,
                          datatype=None, unit=None, source=None):
        """Search active parameters across multiple fields (all filters are AND-ed).

        Each filter is a glob pattern (* and ? supported) or a plain substring.
        Returns a list of row dicts sorted by Name.
        """
        cur = self.conn.cursor()
        clauses = ['(Deleted = 0 OR Deleted IS NULL)']
        args = []

        def _add(col, val):
            if val is None:
                return
            if '*' in val or '?' in val:
                pat = val.replace('*', '%').replace('?', '_')
                clauses.append(f'{col} LIKE ?')
            else:
                pat = f'%{val}%'
                clauses.append(f'{col} LIKE ?')
            args.append(pat)

        _add('Name',        name)
        _add('Description', description)
        _add('DataType',    datatype)
        _add('Unit',        unit)
        _add('Source',      source)

        sql = '''
            SELECT MID, UID, Name, Value, COMMENT, DataType, Unit, Size,
                   Min, Max, Description, ALIASES, ModifiedDateTime,
                   ModificationComment, Who, Users, Source
            FROM calibration
            WHERE ''' + ' AND '.join(clauses) + ' ORDER BY Name'
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _get_all_active(self):
        """Return {name: row_dict} for all non-deleted parameters."""
        cur = self.conn.cursor()
        cur.execute('''
            SELECT MID, UID, Name, Value, COMMENT, DataType, Unit, Size,
                   Min, Max, Description, ALIASES, ModifiedDateTime,
                   ModificationComment, PreviousValues, Who, Users, Source
            FROM calibration WHERE Deleted = 0 OR Deleted IS NULL
        ''')
        cols = [d[0] for d in cur.description]
        return {row[2]: dict(zip(cols, row)) for row in cur.fetchall()}

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def add_parameter(self, prefix, param):
        if not param.name:
            print("Error: Parameter name is required.")
            return False
        uid = prefix + param.name
        mid = hashlib.md5(uid.encode()).hexdigest()
        cur = self.conn.cursor()

        cur.execute('''
            SELECT * FROM calibration
            WHERE Name = ? OR ALIASES LIKE ? OR ALIASES LIKE ? OR ALIASES LIKE ?
        ''', (param.name, param.name, f'%;{param.name}', f'{param.name};%'))
        if cur.fetchone():
            print(f"Warning: Parameter '{param.name}' already exists. Use update to modify.")
            return False

        for w in _validate_value(param.value, param.min_val, param.max_val,
                                  param.datatype, param.size):
            print(f"Warning: {param.name}: {w}")

        try:
            cur.execute('''
                INSERT INTO calibration
                    (MID, UID, Name, Value, COMMENT, DataType, Unit, Size,
                     Min, Max, Description, ALIASES, ModifiedDateTime,
                     ModificationComment, PreviousValues, Deleted, Who, Users, Source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            ''', (mid, uid, param.name, param.value, param.comment,
                  param.datatype, param.unit, param.size,
                  param.min_val, param.max_val, param.description,
                  param.aliases, datetime.now().isoformat(),
                  param.mod_comment, '',
                  param.who, param.users, param.source))
            self._insert_history(cur, param.name, 'add',
                                 new_value=param.value, new_comment=param.comment,
                                 sync_comment=param.mod_comment)
            self._set_db_changed(cur)
            if self.test_mode:
                self.conn.rollback()
            else:
                self.conn.commit()
            print(f"Added: {param.name}")
            return True
        except sqlite3.IntegrityError:
            print(f"Parameter with MID {mid} or UID {uid} already exists.")
            return False

    def update_parameter(self, param):
        if not param.name:
            print("Error: Parameter name is required.")
            return False
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM calibration WHERE Name = ?', (param.name,))
        existing = cur.fetchone()
        if not existing:
            print(f"Parameter '{param.name}' not found. Use add to create.")
            return False

        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, existing))
        old_value = row['Value']
        old_prev = row['PreviousValues'] or ''

        mod_comment = param.mod_comment or ''
        if param.value is not None and _normalise_value(old_value) != _normalise_value(param.value):
            change_str = f"Value: {old_value} -> {param.value}"
            mod_comment = f"{mod_comment} | {change_str}" if mod_comment else change_str

        prev_values = f"{old_prev};{old_value}" if old_prev else old_value or ''
        value = param.value if param.value is not None else old_value

        if param.value is not None:
            for w in _validate_value(value, row.get('Min'), row.get('Max'),
                                     row.get('DataType'), row.get('Size')):
                print(f"Warning: {param.name}: {w}")

        cur.execute('''
            UPDATE calibration
            SET Value = ?, ModifiedDateTime = ?, ModificationComment = ?, PreviousValues = ?
            WHERE MID = ?
        ''', (value, datetime.now().isoformat(), mod_comment, prev_values, row['MID']))
        self._insert_history(cur, param.name, 'update',
                             old_value=old_value, new_value=value,
                             sync_comment=param.mod_comment)
        self._set_db_changed(cur)

        if self.test_mode:
            self.conn.rollback()
        else:
            self.conn.commit()
        print(f"Updated: {param.name}")
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
        cols = [d[0] for d in cur.description]
        r = dict(zip(cols, row))
        old_name = r['Name']
        aliases = r['ALIASES']
        aliases = f"{aliases};{old_name}" if aliases else old_name
        note = f"Name: {old_name} -> {new_name}"
        mod_comment = f"{mod_comment} | {note}" if mod_comment else note
        cur.execute('''
            UPDATE calibration
            SET Name = ?, ALIASES = ?, ModifiedDateTime = ?, ModificationComment = ?
            WHERE MID = ?
        ''', (new_name, aliases, datetime.now().isoformat(), mod_comment, r['MID']))
        self._set_db_changed(cur)
        if self.test_mode:
            self.conn.rollback()
        else:
            self.conn.commit()
        print(f"Renamed: {old_name} -> {new_name}")
        return True

    def soft_delete(self, name, sync_comment=''):
        cur = self.conn.cursor()
        cur.execute('SELECT Value, COMMENT FROM calibration WHERE Name = ?', (name,))
        row = cur.fetchone()
        if row is None:
            print(f"Parameter '{name}' not found.")
            return False
        old_value, old_comment = row
        self._insert_history(cur, name, 'delete',
                             old_value=old_value, old_comment=old_comment,
                             sync_comment=sync_comment)
        cur.execute('''
            UPDATE calibration SET Deleted = 1, ModifiedDateTime = ? WHERE Name = ?
        ''', (datetime.now().isoformat(), name))
        self._set_db_changed(cur)
        if self.test_mode:
            self.conn.rollback()
        else:
            self.conn.commit()
        print(f"Deleted: {name}")
        return True

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def compute_diff(self, csv_file):
        """Compute the diff between a CSV and the current DB state.

        Returns a dict:
          csv_params: {name: CalibrationParameter}  (all rows from CSV)
          db_params:  {name: row_dict}               (all active DB rows)
          added:   [CalibrationParameter, ...]
          changed: [{'name', 'old_value', 'new_value',
                     'old_comment', 'new_comment', 'param'}, ...]
          deleted: [{'name', 'old_value', 'old_comment'}, ...]
        """
        csv_params = {}
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            multicol_format = 'Value_1' in fieldnames
            for row in reader:
                parse = _parse_multicol_row if multicol_format else _parse_standard_row
                p = parse(row)
                if p.name:
                    csv_params[p.name] = p

        db_params = self._get_all_active()

        added = [csv_params[n] for n in csv_params if n not in db_params]

        def _meta_differs(p, db_row):
            """True if any metadata field in the CSV differs from the DB."""
            def _f(v): return '' if v is None else str(v)
            def _fn(v): return None if (v is None or v == '') else float(v)
            return (
                _f(p.datatype)    != _f(db_row.get('DataType'))    or
                _f(p.unit)        != _f(db_row.get('Unit'))        or
                _f(p.size)        != _f(db_row.get('Size'))        or
                _fn(p.min_val)    != _fn(db_row.get('Min'))        or
                _fn(p.max_val)    != _fn(db_row.get('Max'))        or
                _f(p.description) != _f(db_row.get('Description')) or
                _f(p.who)         != _f(db_row.get('Who'))         or
                _f(p.users)       != _f(db_row.get('Users'))       or
                _f(p.source)      != _f(db_row.get('Source'))
            )

        changed = []
        meta_only = []
        for name, p in csv_params.items():
            if name in db_params:
                db_row = db_params[name]
                v_changed = _normalise_value(p.value) != _normalise_value(db_row.get('Value'))
                c_changed = (p.comment or '') != (db_row.get('COMMENT') or '')
                if v_changed or c_changed:
                    changed.append({
                        'name': name,
                        'old_value': db_row.get('Value'),
                        'new_value': p.value,
                        'old_comment': db_row.get('COMMENT'),
                        'new_comment': p.comment,
                        'param': p,
                    })
                elif _meta_differs(p, db_row):
                    meta_only.append({'name': name, 'param': p, 'db_row': db_row})

        deleted = [
            {'name': n,
             'old_value': db_params[n].get('Value'),
             'old_comment': db_params[n].get('COMMENT')}
            for n in db_params if n not in csv_params
        ]

        return {
            'csv_params': csv_params,
            'db_params': db_params,
            'added': added,
            'changed': changed,
            'meta_only': meta_only,
            'deleted': deleted,
        }

    def apply_changes(self, diff, prefix='CAL-', sync_comment='',
                      per_comments=None, only=None):
        """Apply a diff produced by compute_diff.

        per_comments: {name: str}  per-parameter comment, overrides sync_comment
        only:         set of names to process; None means apply everything
        Returns (added, changed, deleted) name lists of what was actually applied.
        """
        per_comments = per_comments or {}
        db_params  = diff['db_params']
        cur = self.conn.cursor()

        def _comment(name):
            return per_comments.get(name, sync_comment)

        applied_added, applied_changed, applied_deleted, applied_meta = [], [], [], []

        for p in diff['added']:
            if only is not None and p.name not in only:
                continue
            for w in _validate_value(p.value, p.min_val, p.max_val, p.datatype, p.size):
                print(f"Warning: {p.name}: {w}")
            comment = _comment(p.name)
            uid = prefix + p.name
            mid = hashlib.md5(uid.encode()).hexdigest()
            try:
                cur.execute('''
                    INSERT INTO calibration
                        (MID, UID, Name, Value, COMMENT, DataType, Unit, Size,
                         Min, Max, Description, ALIASES, ModifiedDateTime,
                         ModificationComment, PreviousValues, Deleted, Who, Users, Source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                ''', (mid, uid, p.name, p.value, p.comment,
                      p.datatype, p.unit, p.size,
                      p.min_val, p.max_val, p.description,
                      None, datetime.now().isoformat(), comment, '',
                      p.who, p.users, p.source))
                self._insert_history(cur, p.name, 'add',
                                     new_value=p.value, new_comment=p.comment,
                                     sync_comment=comment)
                applied_added.append(p.name)
            except sqlite3.IntegrityError:
                print(f"  Skipped (conflict): {p.name}")

        for ch in diff['changed']:
            name = ch['name']
            if only is not None and name not in only:
                continue
            p = ch['param']
            for w in _validate_value(p.value, p.min_val, p.max_val, p.datatype, p.size):
                print(f"Warning: {name}: {w}")
            comment = _comment(name)
            db_row = db_params[name]
            old_value = ch['old_value']
            old_prev = db_row.get('PreviousValues') or ''
            prev_values = f"{old_prev};{old_value}" if old_prev else (old_value or '')
            self._insert_history(cur, name, 'update',
                                 old_value=old_value, new_value=p.value,
                                 old_comment=ch['old_comment'], new_comment=p.comment,
                                 sync_comment=comment)
            cur.execute('''
                UPDATE calibration
                SET Value = ?, COMMENT = ?, DataType = ?, Unit = ?, Size = ?,
                    Min = ?, Max = ?, Description = ?,
                    ModifiedDateTime = ?, ModificationComment = ?, PreviousValues = ?,
                    Who = ?, Users = ?, Source = ?
                WHERE Name = ?
            ''', (p.value, p.comment, p.datatype, p.unit, p.size,
                  p.min_val, p.max_val, p.description,
                  datetime.now().isoformat(), comment, prev_values,
                  p.who, p.users, p.source, name))
            applied_changed.append(name)

        # Metadata-only changes (value/comment unchanged) — update + record
        for m in diff.get('meta_only', []):
            name, p, db_row = m['name'], m['param'], m['db_row']
            if only is not None and name not in only:
                continue
            cur.execute('''
                UPDATE calibration
                SET DataType = ?, Unit = ?, Size = ?, Min = ?, Max = ?,
                    Description = ?, Who = ?, Users = ?, Source = ?
                WHERE Name = ?
            ''', (p.datatype, p.unit, p.size, p.min_val, p.max_val,
                  p.description, p.who, p.users, p.source, name))
            diff_str = _format_meta_diff(p, db_row)
            self._insert_history(cur, name, 'meta', new_value=diff_str,
                                 sync_comment=sync_comment)
            applied_meta.append(name)

        for d in diff['deleted']:
            name = d['name']
            if only is not None and name not in only:
                continue
            comment = _comment(name)
            self._insert_history(cur, name, 'delete',
                                 old_value=d['old_value'], old_comment=d['old_comment'],
                                 sync_comment=comment)
            cur.execute('''
                UPDATE calibration SET Deleted = 1, ModifiedDateTime = ? WHERE Name = ?
            ''', (datetime.now().isoformat(), name))
            applied_deleted.append(name)

        self.conn.commit()
        return applied_added, applied_changed, applied_deleted, applied_meta

    def sync_from_csv(self, csv_file, prefix='CAL-', sync_comment='', dry_run=False):
        """Diff CSV against DB and record all changes.
        Returns (added, changed, deleted, meta_updated) lists of names.
        """
        diff = self.compute_diff(csv_file)
        added        = [p.name for p in diff['added']]
        changed      = [c['name'] for c in diff['changed']]
        deleted      = [d['name'] for d in diff['deleted']]
        meta_updated = [m['name'] for m in diff.get('meta_only', [])]
        if dry_run:
            return added, changed, deleted, meta_updated
        _, _, _, applied_meta = self.apply_changes(
            diff, prefix=prefix, sync_comment=sync_comment)
        self.store_csv_hash(csv_file)
        return added, changed, deleted, applied_meta

    @staticmethod
    def _csv_hash(csv_path):
        h = hashlib.sha256()
        with open(csv_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    def store_csv_hash(self, csv_path):
        """Store a SHA-256 fingerprint of csv_path so sync state can be checked later."""
        digest = self._csv_hash(csv_path)
        cur = self.conn.cursor()
        for key, val in [
            ('csv_hash',      digest),
            ('csv_path',      str(csv_path)),
            ('csv_sync_time', datetime.now().isoformat()),
        ]:
            cur.execute(
                'INSERT OR REPLACE INTO _caldb_meta (key, value) VALUES (?, ?)',
                (key, val),
            )
        cur.execute("DELETE FROM _caldb_meta WHERE key = 'db_changed'")
        self.conn.commit()

    def get_db_changed_time(self):
        """Return ISO timestamp of last CLI write since sync, or None if in sync."""
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM _caldb_meta WHERE key = 'db_changed'")
        row = cur.fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def tag_snapshot(self, name, comment='', at=None):
        """Create a named tag at a point in time.

        at -- ISO datetime string to backdate the tag; defaults to now.
        Returns False (and prints a warning) if the tag name already exists.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT name FROM _caldb_tags WHERE name = ?", (name,))
        if cur.fetchone():
            print(f"Tag '{name}' already exists.")
            return False
        dt = at if at else datetime.now().isoformat()
        cur.execute(
            "INSERT INTO _caldb_tags (name, ChangeDateTime, comment) VALUES (?, ?, ?)",
            (name, dt, comment),
        )
        self.conn.commit()
        backdated = '  (backdated)' if at else ''
        print(f"Tagged: {name}  ({dt[:19].replace('T', ' ')}){backdated}")
        return True

    def list_tags(self):
        """Return all tags as a list of dicts, oldest first."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT name, ChangeDateTime, comment FROM _caldb_tags ORDER BY ChangeDateTime"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_parameters_at_tag(self, tag_name, pattern=None):
        """Return (tag_datetime_str, [row_dict, ...]) for parameters at a tag.

        Value and Comment are taken from history (what they were at that time).
        DataType, Unit, Size, Min, Max, Description, Source come from the
        current calibration table (these fields are not tracked in history).

        Returns (None, None) if the tag does not exist.
        Parameters that were deleted before the tag time are excluded.
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT ChangeDateTime FROM _caldb_tags WHERE name = ?", (tag_name,)
        )
        row = cur.fetchone()
        if row is None:
            return None, None
        tag_time = row[0]

        cur.execute('''
            SELECT h.Name,
                   h.NewValue    AS Value,
                   h.NewComment  AS COMMENT,
                   c.DataType, c.Unit, c.Size, c.Min, c.Max,
                   c.Description, c.Who, c.Source
            FROM calibration_history h
            LEFT JOIN calibration c ON c.Name = h.Name
            WHERE h.id IN (
                SELECT MAX(id) FROM calibration_history
                WHERE ChangeDateTime <= ?
                GROUP BY Name
            )
            AND h.ChangeType != 'delete'
            ORDER BY h.Name
        ''', (tag_time,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        if pattern:
            if '*' in pattern or '?' in pattern:
                rows = [r for r in rows if fnmatch.fnmatch(r['Name'], pattern)]
            else:
                rows = [r for r in rows if r['Name'] == pattern]

        return tag_time, rows

    def get_sync_status(self, csv_path):
        """Compare csv_path's current content against the stored hash.

        Returns (in_sync, last_sync_time):
          in_sync        True  = matches last sync
                         False = CSV has changed since last sync
                         None  = no sync recorded yet, or CSV not found
          last_sync_time ISO string of last sync, or None if never synced
        """
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM _caldb_meta WHERE key = 'csv_hash'")
        row = cur.fetchone()
        if not row:
            return None, None
        stored_hash = row[0]
        cur.execute("SELECT value FROM _caldb_meta WHERE key = 'csv_sync_time'")
        time_row = cur.fetchone()
        last_sync_time = time_row[0] if time_row else None
        try:
            current_hash = self._csv_hash(csv_path)
        except OSError:
            return None, last_sync_time
        return current_hash == stored_hash, last_sync_time

    def compute_db_to_csv_diff(self, csv_path):
        """Compute changes needed to bring the CSV in sync with the current DB.

        Returns:
          fieldnames:  list of CSV column headers (preserves format)
          multicol:    True if multi-column format was detected
          changed:     [{'name', 'csv_value', 'db_value',
                          'csv_comment', 'db_comment', 'db_row'}, ...]
          to_add:      [db_row_dict, ...]  (active in DB, absent from CSV)
          to_delete:   [name, ...]          (in CSV, absent from active DB)
        """
        fieldnames = []
        multicol = False
        csv_params = {}
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])
            multicol = 'Value_1' in fieldnames
            for row in reader:
                parse = _parse_multicol_row if multicol else _parse_standard_row
                p = parse(row)
                if p.name:
                    csv_params[p.name] = p

        db_params = self._get_all_active()

        changed = []
        for name, p in csv_params.items():
            if name in db_params:
                db_row = db_params[name]
                v_diff = _normalise_value(db_row.get('Value')) != _normalise_value(p.value)
                c_diff = (db_row.get('COMMENT') or '') != (p.comment or '')
                if v_diff or c_diff:
                    changed.append({
                        'name': name,
                        'csv_value': p.value,
                        'db_value': db_row.get('Value'),
                        'csv_comment': p.comment,
                        'db_comment': db_row.get('COMMENT'),
                        'db_row': db_row,
                    })

        to_add = [db_params[n] for n in db_params if n not in csv_params]
        to_delete = [n for n in csv_params if n not in db_params]

        return {
            'fieldnames': fieldnames,
            'multicol': multicol,
            'changed': changed,
            'to_add': to_add,
            'to_delete': to_delete,
        }

    def write_back_to_csv(self, csv_path, diff):
        """Rewrite csv_path to match the DB state described by diff.

        Updates values/comments for changed rows; appends rows for to_add.
        Rows in to_delete are left as-is (reported but not removed).
        Values are canonicalised on write.
        """
        fieldnames     = diff['fieldnames']
        multicol       = diff['multicol']
        name_to_change = {ch['name']: ch for ch in diff['changed']}

        rows = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))

        for row in rows:
            name = row.get('Name', '').strip()
            if name not in name_to_change:
                continue
            ch = name_to_change[name]
            canonical = _canonicalise_value(ch['db_value'])
            if multicol:
                for col in _VALUE_COLS:
                    row[col] = ''
                for i, part in enumerate(canonical.split()[:10]):
                    row[f'Value_{i + 1}'] = part
            else:
                elems = canonical.split()
                row['Value'] = ('[' + ' '.join(elems) + ']') if len(elems) > 1 else canonical
            if 'COMMENT' in row:
                row['COMMENT'] = ch['db_comment'] or ''

        for db_row in diff['to_add']:
            new_row = {f: '' for f in fieldnames}
            new_row['Name'] = db_row['Name']
            canonical = _canonicalise_value(db_row.get('Value') or '')
            if multicol:
                for i, part in enumerate(canonical.split()[:10]):
                    new_row[f'Value_{i + 1}'] = part
            else:
                elems = canonical.split()
                new_row['Value'] = ('[' + ' '.join(elems) + ']') if len(elems) > 1 else canonical
            new_row['COMMENT']     = db_row.get('COMMENT') or ''
            new_row['DataType']    = db_row.get('DataType') or ''
            new_row['Unit']        = db_row.get('Unit') or ''
            new_row['Size']        = db_row.get('Size') or ''
            mn, mx = db_row.get('Min'), db_row.get('Max')
            new_row['Min'] = '' if mn is None else (str(int(mn)) if mn == int(mn) else str(mn))
            new_row['Max'] = '' if mx is None else (str(int(mx)) if mx == int(mx) else str(mx))
            new_row['Description'] = db_row.get('Description') or ''
            rows.append(new_row)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

    # ------------------------------------------------------------------
    # History log
    # ------------------------------------------------------------------

    def get_parameter_log(self, name, limit=20):
        """Return change history for a parameter, newest first."""
        cur = self.conn.cursor()
        cur.execute('''
            SELECT id, Name, ChangeType, OldValue, NewValue, OldComment, NewComment,
                   ChangeDateTime, SyncComment
            FROM calibration_history
            WHERE Name = ?
            ORDER BY id DESC
            LIMIT ?
        ''', (name, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_recent_changes(self, limit=10, since=None):
        """Return recent changes across all parameters, newest first.

        limit  0 = all entries
        since  ISO date string  e.g. '2026-06-01'  -> ChangeDateTime >= that date
               sync comment str e.g. 'sprint 4'    -> on or after that sync session
        """
        cur = self.conn.cursor()
        since_dt = None
        if since:
            if since[:4].isdigit() and '-' in since:
                since_dt = since  # treat as date/datetime prefix
            else:
                cur.execute(
                    "SELECT MIN(ChangeDateTime) FROM calibration_history WHERE SyncComment = ?",
                    (since,),
                )
                row = cur.fetchone()
                since_dt = row[0] if row and row[0] else None

        base = '''
            SELECT id, Name, ChangeType, OldValue, NewValue, OldComment, NewComment,
                   ChangeDateTime, SyncComment
            FROM calibration_history
        '''
        where = 'WHERE ChangeDateTime >= ? ' if since_dt else ''
        order = 'ORDER BY id DESC'
        limit_clause = '' if limit == 0 else f'LIMIT {int(limit)}'

        args = (since_dt,) if since_dt else ()
        cur.execute(f'{base} {where} {order} {limit_clause}', args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def annotate_changes(self, message, since=None, until=None, entry_id=None):
        """Update SyncComment on history rows.

        Exactly one selector must be provided:
          entry_id  -- update a single row by id
          since     -- update all rows with ChangeDateTime >= since
                       optionally combined with until (< until)

        since/until may use either 'T' or ' ' as the date-time separator;
        both are normalised to 'T' to match the stored ISO format.

        Returns the number of rows updated.
        """
        def _norm(dt):
            # Replace first space with T so "2026-06-08 14:10" matches stored ISO
            if dt and len(dt) > 10 and dt[10] == ' ':
                return dt[:10] + 'T' + dt[11:]
            return dt

        cur = self.conn.cursor()
        if entry_id is not None:
            cur.execute(
                'UPDATE calibration_history SET SyncComment=? WHERE id=?',
                (message, entry_id),
            )
        elif since is not None:
            since = _norm(since)
            if until is not None:
                cur.execute(
                    'UPDATE calibration_history SET SyncComment=? '
                    'WHERE ChangeDateTime >= ? AND ChangeDateTime < ?',
                    (message, since, _norm(until)),
                )
            else:
                cur.execute(
                    'UPDATE calibration_history SET SyncComment=? '
                    'WHERE ChangeDateTime >= ?',
                    (message, since),
                )
        else:
            raise ValueError("Provide entry_id or since.")
        self.conn.commit()
        return cur.rowcount

    def annotate_many(self, updates):
        """Apply a list of (id, new_comment) updates to calibration_history.

        updates  -- iterable of (entry_id, message) pairs
        Returns the number of rows updated.
        """
        cur = self.conn.cursor()
        count = 0
        for entry_id, message in updates:
            cur.execute(
                'UPDATE calibration_history SET SyncComment=? WHERE id=?',
                (message, entry_id),
            )
            count += cur.rowcount
        self.conn.commit()
        return count

    # ------------------------------------------------------------------
    # Import / Export (existing)
    # ------------------------------------------------------------------

    def load_from_csv(self, csv_file, prefix='CAL-', delimiter=','):
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            fieldnames = reader.fieldnames or []
            multicol_format = 'Value_1' in fieldnames
            for row in reader:
                parse = _parse_multicol_row if multicol_format else _parse_standard_row
                p = parse(row)
                self.add_parameter(prefix, p)

    def load_from_json(self, json_file, prefix='CAL-'):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, list):
                data = [data]
            for item in data:
                min_val = float(item['Min']) if item.get('Min', '') else None
                max_val = float(item['Max']) if item.get('Max', '') else None
                param = CalibrationParameter(
                    name=item.get('Name'),
                    value=item.get('Value'),
                    comment=item.get('COMMENT'),
                    datatype=item.get('DataType'),
                    unit=item.get('Unit'),
                    size=item.get('Size'),
                    min_val=min_val,
                    max_val=max_val,
                    description=item.get('Description'),
                    aliases=item.get('ALIASES'),
                    mod_comment=item.get('ModificationComment'),
                    who=None, users=None, source=None,
                )
                self.add_parameter(prefix, param)

    def export_to_csv(self, csv_file, delimiter=','):
        cur = self.conn.cursor()
        cur.execute('SELECT * FROM calibration WHERE Deleted = 0 OR Deleted IS NULL')
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f"Exported to {csv_file}")

    def close(self):
        if self.test_mode:
            print("Test mode: rolling back.")
            self.conn.rollback()
        self.conn.close()
