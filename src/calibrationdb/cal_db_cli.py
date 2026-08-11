import glob
import os
import stat
import subprocess
from enum import Enum
from typing import List, Optional

import click
import typer
from rich import box
from rich.console import Console
from rich.table import Table

from .cal_db_util import CalibrationDatabase, CalibrationParameter, _format_meta_diff, _load_csv_params

# Fixed (large) width so rich never shrinks/crops columns to fit the detected
# terminal size -- matches the old manual table printers, which always printed
# full-width rows and let the terminal itself wrap/scroll long lines.
_console = Console(width=300)


class ChangeType(str, Enum):
    ADD = 'add'
    UPDATE = 'update'
    DELETE = 'delete'
    RESTORE = 'restore'
    META = 'meta'


class FileFormat(str, Enum):
    CSV = 'csv'
    JSON = 'json'


_HOOK_MARKER_START = '# >>> caldb pre-commit hook'
_HOOK_MARKER_END   = '# <<< caldb pre-commit hook'

# sh script; Python is used for logic so it works cross-platform via Git's sh
_HOOK_BODY = r"""
# >>> caldb pre-commit hook
python -c "
import subprocess, sys, os

root = subprocess.run(
    ['git', 'rev-parse', '--show-toplevel'],
    capture_output=True, text=True
).stdout.strip()
if not root:
    sys.exit(0)

staged = subprocess.run(
    ['git', 'diff', '--name-only', '--cached', '--diff-filter=ACM'],
    capture_output=True, text=True, cwd=root
).stdout.splitlines()

csv_files = [f for f in staged if f.lower().endswith('.csv')]
if not csv_files:
    sys.exit(0)

errors = False
for csv_rel in csv_files:
    csv_abs = os.path.join(root, csv_rel)
    db_abs  = os.path.splitext(csv_abs)[0] + '.db'
    if not os.path.exists(db_abs):
        continue
    r = subprocess.run(['caldb', '-d', db_abs, 'sync', '-f', csv_abs], cwd=root)
    if r.returncode != 0:
        errors = True
    else:
        subprocess.run(
            ['git', 'add', os.path.splitext(csv_rel)[0] + '.db'], cwd=root
        )

sys.exit(1 if errors else 0)
"
# <<< caldb pre-commit hook
"""


def _resolve_db(db):
    """Resolve DB path for commands that don't need a CSV.
    Prefers a DB that has a matching .csv in the same directory."""
    if db:
        return db
    db_files = glob.glob('*.db')
    paired = [f for f in db_files if os.path.exists(os.path.splitext(f)[0] + '.csv')]
    candidates = paired if paired else db_files
    if len(candidates) == 1:
        click.echo(f"Using DB: {candidates[0]}")
        return candidates[0]
    if len(candidates) > 1:
        names = ', '.join(candidates)
        raise typer.BadParameter(f"Multiple DB files found ({names}). Specify --db.")
    raise typer.BadParameter("No .db file found. Provide --db <path>.")


def _resolve_pair(db, csv_file, allow_new_db=False):
    """Resolve (db_path, csv_path), deriving each from the other when omitted.

    Priority:
      both given          -> use as-is
      only --db           -> csv = same base name + .csv
      only --file         -> db  = same base name + .db
                             (created automatically when allow_new_db=True,
                              otherwise must already exist)
      neither given       -> scan cwd for a matched .db/.csv pair
    """
    if db and csv_file:
        return db, csv_file

    if db:
        return db, os.path.splitext(db)[0] + '.csv'

    if csv_file:
        db_candidate = os.path.splitext(csv_file)[0] + '.db'
        if not os.path.exists(db_candidate):
            if allow_new_db:
                click.echo(f"Creating DB: {db_candidate}")
            else:
                raise typer.BadParameter(
                    f"No matching DB found at '{db_candidate}'. Provide --db."
                )
        else:
            click.echo(f"Using DB: {db_candidate}")
        return db_candidate, csv_file

    # Neither given: look for a matched pair in cwd
    db_files = glob.glob('*.db')
    pairs = [
        (f, os.path.splitext(f)[0] + '.csv')
        for f in db_files
        if os.path.exists(os.path.splitext(f)[0] + '.csv')
    ]
    if len(pairs) == 1:
        click.echo(f"Auto: {pairs[0][0]} / {os.path.basename(pairs[0][1])}")
        return pairs[0]
    if len(pairs) > 1:
        names = ', '.join(os.path.basename(p[0]) for p in pairs)
        raise typer.BadParameter(f"Multiple DB/CSV pairs found ({names}). Specify --db.")
    # No matched pairs -- fall back to any single .db
    if len(db_files) == 1:
        click.echo(f"Using DB: {db_files[0]}")
        return db_files[0], os.path.splitext(db_files[0])[0] + '.csv'
    if db_files:
        names = ', '.join(db_files)
        raise typer.BadParameter(f"Multiple DB files found ({names}). Specify --db.")
    raise typer.BadParameter("No .db file found. Provide --db <path>.")


def _warn_if_unsynced(db_path):
    """Print a warning if the CSV associated with db_path has changed since last sync."""
    csv_path = os.path.splitext(db_path)[0] + '.csv'
    if not os.path.exists(csv_path):
        return
    db = CalibrationDatabase(db_path)
    in_sync, last_sync_time = db.get_sync_status(csv_path)
    db.close()
    if in_sync is False:
        ts = last_sync_time[:19].replace('T', ' ') if last_sync_time else 'never'
        click.secho(
            f"Warning: CSV has changed since last sync ({ts}). Run 'caldb sync' first.",
            fg='yellow', err=True,
        )


def _git_file_status(path):
    """Return the git working-tree status of a file.

    Returns one of: 'clean', 'modified', 'staged', 'both', 'untracked',
    or None if git is unavailable or the file is not in a repo.
    """
    abs_path = os.path.abspath(path)
    fname = os.path.basename(abs_path)
    # Run from the file's own directory and pass just the basename with '--'
    # so git doesn't misinterpret an absolute Windows path as a flag.
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain', '--', fname],
            capture_output=True, text=True,
            cwd=os.path.dirname(abs_path) or '.',
        )
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        # Verify the line actually refers to our file (defensive against edge cases)
        file_in_line = line[3:].strip().replace('/', os.sep)
        if os.path.basename(file_in_line) != fname:
            continue
        x, y = line[0], line[1]
        if x == '?' and y == '?':
            return 'untracked'
        if x != ' ' and y != ' ':
            return 'both'
        if x != ' ':
            return 'staged'
        if y != ' ':
            return 'modified'
        return 'clean'
    return 'clean'


def _print_sync_report(added, changed, deleted, meta_updated=None, dry_run=False):
    meta_updated = meta_updated or []
    tag = '[DRY RUN] ' if dry_run else ''
    total = len(added) + len(changed) + len(deleted)
    meta_str = f", {len(meta_updated)} meta updated" if meta_updated else ""
    click.echo(f"{tag}Sync: {len(added)} added, {len(changed)} changed, "
               f"{len(deleted)} deleted{meta_str} ({total} total)")
    if added:
        click.echo("\nADDED:")
        for n in added:
            click.echo(f"  + {n}")
    if changed:
        click.echo("\nCHANGED:")
        for n in changed:
            click.echo(f"  ~ {n}")
    if deleted:
        click.echo("\nDELETED:")
        for n in deleted:
            click.echo(f"  - {n}")
    if meta_updated:
        click.echo("\nMETA UPDATED:")
        for n in meta_updated:
            click.echo(f"  * {n}")


app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode='rich',
    pretty_exceptions_enable=False,
    add_completion=False,
)


@app.callback()
def cli(
    ctx: typer.Context,
    db: Optional[str] = typer.Option(None, '--db', '-d', help='Database file path'),
    test: bool = typer.Option(False, '--test', help='Dry-run: rollback all changes'),
):
    ctx.obj = {'db': db, 'test': test}


@app.command()
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., '--name', '-n', help='Parameter name'),
    value: Optional[str] = typer.Option(None, '--value', '-v', help='Parameter value'),
    comment: Optional[str] = typer.Option(None, '--comment', '-c', help='Comment'),
    datatype: Optional[str] = typer.Option(None, '--datatype', help='Data type (uint8, single, boolean, …)'),
    unit: Optional[str] = typer.Option(None, '--unit', '-u', help='Unit'),
    size: Optional[str] = typer.Option(None, '--size', help='Array size'),
    min_val: Optional[float] = typer.Option(None, '--min', help='Minimum value'),
    max_val: Optional[float] = typer.Option(None, '--max', help='Maximum value'),
    description: Optional[str] = typer.Option(None, '--description', help='Description'),
    aliases: Optional[str] = typer.Option(None, '--aliases', help='Aliases (semicolon-separated)'),
    prefix: str = typer.Option('CAL-', '--prefix', '-p', help='UID prefix', show_default=True),
    mod_comment: Optional[str] = typer.Option(None, '--mod-comment', '-m', help='Modification comment'),
):
    """Add a new parameter."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    param = CalibrationParameter(
        name=name, value=value, comment=comment, datatype=datatype,
        unit=unit, size=size, min_val=min_val, max_val=max_val,
        description=description, aliases=aliases, mod_comment=mod_comment,
    )
    db.add_parameter(prefix, param)
    db.close()


@app.command()
def update(
    ctx: typer.Context,
    name: str = typer.Option(..., '--name', '-n', help='Parameter name'),
    value: Optional[str] = typer.Option(None, '--value', '-v', help='New value'),
    mod_comment: Optional[str] = typer.Option(None, '--mod-comment', '-m', help='Modification comment'),
):
    """Update the value of an existing parameter."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.update_parameter(CalibrationParameter(name=name, value=value, mod_comment=mod_comment))
    db.close()


@app.command()
def rename(
    ctx: typer.Context,
    identifier: str = typer.Option(..., '--identifier', '-i', help='MID, UID, or Name'),
    new_name: str = typer.Option(..., '--new-name', help='New parameter name'),
    mod_comment: str = typer.Option('', '--mod-comment', '-m', help='Modification comment'),
):
    """Rename a parameter (old name moves to aliases)."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.rename_parameter(identifier, new_name, mod_comment)
    db.close()


@app.command()
def delete(
    ctx: typer.Context,
    name: str = typer.Option(..., '--name', '-n', help='Parameter name'),
    comment: str = typer.Option('', '--comment', '-c', help='Reason for deletion'),
):
    """Soft-delete a parameter (kept in history)."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.soft_delete(name, comment)
    db.close()


@app.command()
def review(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, '--file', '-f', help='CSV file to review'),
    prefix: str = typer.Option('CAL-', '--prefix', '-p', show_default=True),
):
    """Interactively review each change before it is written to the DB.

    \b
    For every added, changed, or deleted parameter you can:
      Enter          confirm; uses the parameter's COMMENT column as sync comment
      <any text>     confirm and use that text as the sync comment
      s              skip (do not apply this change)
      q              stop reviewing and apply everything confirmed so far
      a              abort -- apply nothing

    See also: caldb annotate  -- retroactively label changes already in history
    """
    db_path, file = _resolve_pair(ctx.obj['db'], file)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    diff = db.compute_diff(file)

    added   = diff['added']
    changed = diff['changed']
    deleted = diff['deleted']
    total   = len(added) + len(changed) + len(deleted)

    if total == 0:
        click.echo("Nothing to review -- DB is up to date.")
        db.close()
        return

    click.echo(
        f"\n{total} change(s) to review  "
        f"({len(added)} added, {len(changed)} changed, {len(deleted)} deleted)\n"
        f"Enter=confirm | <text>=confirm with comment | s=skip | q=quit&apply | a=abort\n"
    )

    confirmed = set()
    per_comments = {}
    aborted = False

    def _prompt_change(idx, label, detail_lines, default_comment=''):
        """Show one change and return (action, comment).
        action: 'confirm' | 'skip' | 'quit' | 'abort'
        Pressing Enter with no input keeps default_comment as the sync comment.
        """
        click.echo(f"--- [{idx}/{total}]  {label}")
        for line in detail_lines:
            click.echo(f"    {line}")
        if default_comment:
            prompt_text = f"    sync comment [{default_comment}]"
            raw = click.prompt(prompt_text, default=default_comment,
                               show_default=False, prompt_suffix=' > ')
        else:
            raw = click.prompt("    sync comment", default='',
                               show_default=False, prompt_suffix=' > ')
        raw = raw.strip()
        if raw.lower() == 'a':
            return 'abort', ''
        if raw.lower() == 'q':
            return 'quit', ''
        if raw.lower() == 's':
            return 'skip', ''
        return 'confirm', raw

    def _fmt(v):
        return v if v is not None else '(none)'

    items = (
        [('ADD',    p.name,
          [f"value:    {_fmt(p.value)}",
           f"comment:  {_fmt(p.comment)}"],
          p.comment or '')
         for p in added] +
        [('UPDATE', c['name'],
          [f"value:    {_fmt(c['old_value'])}  ->  {_fmt(c['new_value'])}"] +
          ([f"comment:  {_fmt(c['old_comment'])}  ->  {_fmt(c['new_comment'])}"]
           if (c['old_comment'] or '') != (c['new_comment'] or '') else []),
          c['new_comment'] or c['old_comment'] or '')
         for c in changed] +
        [('DELETE', d['name'],
          [f"value:    {_fmt(d['old_value'])}",
           f"comment:  {_fmt(d['old_comment'])}"],
          d['old_comment'] or '')
         for d in deleted]
    )

    for idx, (ctype, name, details, default_cmt) in enumerate(items, 1):
        action, cmt = _prompt_change(idx, f"{ctype:6s}  {name}", details, default_cmt)
        if action == 'abort':
            aborted = True
            break
        if action == 'quit':
            break
        if action == 'confirm':
            confirmed.add(name)
            if cmt:
                per_comments[name] = cmt
        # 'skip' -> name stays out of confirmed

    click.echo()
    if aborted:
        click.echo("Aborted -- nothing written.")
        db.close()
        return

    if not confirmed:
        click.echo("Nothing confirmed -- nothing written.")
        db.close()
        return

    applied_added, applied_changed, applied_deleted, applied_meta = db.apply_changes(
        diff, prefix=prefix, only=confirmed, per_comments=per_comments,
    )
    db.close()
    _print_sync_report(applied_added, applied_changed, applied_deleted,
                       meta_updated=applied_meta)


@app.command()
def load(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, '--file', '-f', help='CSV or JSON file path'),
    prefix: str = typer.Option('CAL-', '--prefix', '-p', show_default=True),
    fmt: Optional[FileFormat] = typer.Option(
        None, '--type', help='File format (default: inferred from extension)',
    ),
):
    """Bulk-load parameters from a CSV or JSON file."""
    db_path, file = _resolve_pair(ctx.obj['db'], file, allow_new_db=True)
    if fmt is None:
        fmt = FileFormat.JSON if file.lower().endswith('.json') else FileFormat.CSV
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    if fmt == 'csv':
        db.load_from_csv(file, prefix)
    else:
        db.load_from_json(file, prefix)
    db.close()


@app.command()
def sync(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, '--file', '-f', help='CSV file to sync from/to'),
    prefix: str = typer.Option('CAL-', '--prefix', '-p', show_default=True),
    comment: str = typer.Option('', '--comment', '-c', help='Comment stored with all changes (CSV->DB only)'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Show what would change without writing'),
    to_csv: bool = typer.Option(
        False, '--to-csv',
        help='Write DB changes back to CSV instead of the default CSV->DB direction',
    ),
):
    """Sync DB with CSV.

    \b
    Default direction:  CSV -> DB  (record CSV edits in the database)
    Reverse direction:  DB  -> CSV (write CLI edits back to the CSV file)

    Direction is auto-detected when omitted:
      only CSV changed  ->  CSV -> DB
      only DB changed   ->  DB  -> CSV  (same as --to-csv)
      both changed      ->  conflict warning, manual resolution required
    """
    db_path, csv_path = _resolve_pair(ctx.obj['db'], file, allow_new_db=True)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])

    # Auto-detect direction unless --to-csv was given explicitly
    if not to_csv:
        csv_in_sync, _ = db.get_sync_status(csv_path)
        db_changed_time = db.get_db_changed_time()
        csv_changed = csv_in_sync is False
        db_changed  = db_changed_time is not None

        if db_changed and not csv_changed:
            click.echo("Auto-detected: DB changed via CLI -- writing back to CSV.")
            to_csv = True
        elif db_changed and csv_changed:
            click.secho(
                "Both CSV and DB changed since last sync -- conflict.\n"
                "Use --to-csv to overwrite CSV with DB values, or edit manually.",
                fg='yellow', err=True,
            )
            db.close()
            ctx.exit(3)

    if to_csv:
        if not os.path.exists(csv_path):
            click.echo(f"CSV not found: {csv_path}")
            db.close()
            ctx.exit(1)

        # Git guard: warn if CSV has uncommitted changes
        git_st = _git_file_status(csv_path)
        if git_st in ('modified', 'both'):
            click.secho(
                f"Warning: {os.path.basename(csv_path)} has uncommitted changes in git.",
                fg='yellow', err=True,
            )
            if not click.confirm("Overwrite anyway?", default=False):
                db.close()
                return

        diff = db.compute_db_to_csv_diff(csv_path)
        n_changed  = len(diff['changed'])
        n_add      = len(diff['to_add'])
        n_del_warn = len(diff['to_delete'])

        if n_changed == 0 and n_add == 0:
            if n_del_warn:
                click.echo(
                    f"Nothing to write back -- {n_del_warn} CSV row(s) not in active DB "
                    f"(soft-deleted or not yet synced)."
                )
            else:
                click.echo("Nothing to write back -- CSV matches DB.")
            if not dry_run and not ctx.obj['test']:
                db.store_csv_hash(csv_path)
            db.close()
            return

        tag = '[DRY RUN] ' if dry_run else ''
        click.echo(
            f"{tag}DB -> CSV: {n_add} to add, {n_changed} to update"
            + (f", {n_del_warn} CSV-only row(s) left as-is" if n_del_warn else '')
        )

        if dry_run or ctx.obj['test']:
            if diff['changed']:
                click.echo("\nUPDATE:")
                for ch in diff['changed']:
                    click.echo(f"  ~ {ch['name']}:  {ch['csv_value']}  ->  {ch['db_value']}")
            if diff['to_add']:
                click.echo("\nADD to CSV:")
                for r in diff['to_add']:
                    click.echo(f"  + {r['Name']}  ({r.get('Value')})")
            if diff['to_delete']:
                click.echo("\nCSV-only (not in active DB -- left as-is):")
                for n in diff['to_delete']:
                    click.echo(f"  ? {n}")
            db.close()
            return

        # Interactive per-change confirmation
        items = (
            [('UPDATE', ch['name'], f"{ch['csv_value']} -> {ch['db_value']}")
             for ch in diff['changed']] +
            [('ADD',    r['Name'],  f"value: {r.get('Value')}")
             for r in diff['to_add']]
        )

        accepted = set()
        accept_all = False
        click.echo("\nConfirm each change  (y=yes  n=skip  a=accept all  q=quit):\n")
        for ctype, name, detail in items:
            if accept_all:
                accepted.add(name)
                continue
            click.echo(f"  {ctype:6s}  {name}  ({detail})")
            raw = click.prompt("  ", default='y', show_default=False,
                               prompt_suffix='[y/n/a/q] > ').strip().lower()
            if raw == 'q':
                break
            if raw == 'a':
                accept_all = True
                accepted.add(name)
            elif raw in ('y', ''):
                accepted.add(name)

        if not accepted:
            click.echo("\nNothing accepted -- CSV unchanged.")
            db.close()
            return

        diff['changed'] = [ch for ch in diff['changed'] if ch['name'] in accepted]
        diff['to_add']  = [r  for r  in diff['to_add']  if r['Name']  in accepted]

        db.write_back_to_csv(csv_path, diff)
        db.store_csv_hash(csv_path)
        click.echo(
            f"\nWrote back: {len(diff['to_add'])} added, "
            f"{len(diff['changed'])} updated -> {os.path.basename(csv_path)}"
        )

    else:
        # Default: CSV -> DB
        added, changed, deleted, meta_updated = db.sync_from_csv(
            csv_path, prefix=prefix, sync_comment=comment, dry_run=dry_run,
        )
        _print_sync_report(added, changed, deleted,
                           meta_updated=meta_updated, dry_run=dry_run)

    db.close()


@app.command()
def export(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, '--file', '-f', help='Output CSV file path'),
):
    """Export the database to CSV."""
    db_path, file = _resolve_pair(ctx.obj['db'], file)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.export_to_csv(file)
    db.close()


@app.command()
def validate(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(
        None, '--name', '-n', help='Parameter name or glob pattern. Omit to check all.',
    ),
):
    """Check parameter values against their Min/Max/DataType/Size constraints."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    results = db.validate_parameters(name)
    db.close()

    if not results:
        label = f"matching '{name}'" if name else "all parameters"
        click.echo(f"OK -- no constraint violations ({label}).")
        return

    click.echo(f"{len(results)} parameter(s) with violations:\n")
    for r in results:
        click.secho(f"  {r['name']}  ({r['value']})", bold=True)
        for w in r['warnings']:
            click.echo(f"    ! {w}")
    ctx.exit(1)


def _print_param_rows(rows, compact, table=False):
    """Shared display logic for show and search."""
    if compact:
        for r in rows:
            click.echo(f"{r['Name']}={r['Value']}")
        return

    if table:
        _TVAL = 24
        _TDESC = 30

        def range_str(r):
            mn = r.get('Min')
            mx = r.get('Max')
            if mn is None and mx is None:
                return ''
            return f"{'' if mn is None else mn}..{'' if mx is None else mx}"

        trows = [{
            'name':  r['Name'],
            'value': _trunc(r.get('Value') or '', _TVAL),
            'type':  r.get('DataType') or '',
            'unit':  r.get('Unit') or '',
            'range': range_str(r),
            'desc':  _trunc(r.get('Description') or '', _TDESC),
            'cmt':   _trunc(r.get('COMMENT') or '', _TDESC),
        } for r in rows]

        columns = [('name', 'Name'), ('value', 'Value')]
        if any(r['type']  for r in trows): columns.append(('type',  'DataType'))
        if any(r['unit']  for r in trows): columns.append(('unit',  'Unit'))
        if any(r['range'] for r in trows): columns.append(('range', 'Range'))
        if any(r['desc']  for r in trows): columns.append(('desc',  'Description'))
        if any(r['cmt']   for r in trows): columns.append(('cmt',   'Comment'))

        _print_table(columns, trows)
        return

    for r in rows:
        click.echo(f"{r['Name']}")
        click.echo(f"  value:    {r['Value']}")
        parts = []
        if r.get('DataType'): parts.append(r['DataType'])
        if r.get('Unit'):     parts.append(r['Unit'])
        if r.get('Size'):     parts.append(f"size={r['Size']}")
        if parts:
            click.echo(f"  type:     {', '.join(parts)}")
        if r.get('Min') is not None or r.get('Max') is not None:
            click.echo(f"  range:    {r['Min']} .. {r['Max']}")
        if r.get('Description'):
            click.echo(f"  desc:     {r['Description']}")
        if r.get('COMMENT'):
            click.echo(f"  comment:  {r['COMMENT']}")
        if r.get('Who') or r.get('Source'):
            who_src = '  /  '.join(x for x in [r.get('Who'), r.get('Source')] if x)
            click.echo(f"  who/src:  {who_src}")
        click.echo()


@app.command()
def show(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(
        None, '--name', '-n', help='Parameter name or glob pattern (e.g. "FanSpd*"). Omit to show all.',
    ),
    compact: bool = typer.Option(False, '--compact', '-c', help='One line per parameter: Name=Value'),
    table: bool = typer.Option(
        False, '--table', '-T', help='Aligned table view (default; kept for backward compatibility)',
    ),
    detail: bool = typer.Option(
        False, '--detail', '-v', help='Show the old multi-line detailed view instead of the table',
    ),
    at: Optional[str] = typer.Option(
        None, '--at', metavar='TAG', help='Show values as they were at a named tag (see: caldb tags)',
    ),
):
    """Show current value and metadata for one or more parameters."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])

    if at:
        tag_time, rows = db.get_parameters_at_tag(at, pattern=name)
        db.close()
        if tag_time is None:
            click.echo(f"Tag '{at}' not found. Use 'caldb tags' to list available tags.")
            return
        if not rows:
            msg = (f"No parameters matching '{name}' at tag '{at}'."
                   if name else f"No parameters recorded at tag '{at}'.")
            click.echo(msg)
            return
        ts = tag_time[:19].replace('T', ' ')
        click.echo(f"[at tag '{at}'  --  {ts}]\n")
    else:
        rows = db.get_parameters(name)
        db.close()
        if not rows:
            msg = f"No parameter found matching '{name}'." if name else "No parameters in DB."
            click.echo(msg)
            return

    _print_param_rows(rows, compact, table=not detail)


@app.command()
def search(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, '--name', '-n', help='Name glob pattern (e.g. "*derate*")'),
    description: Optional[str] = typer.Option(
        None, '--description', '-D', help='Description contains or glob pattern',
    ),
    datatype: Optional[str] = typer.Option(
        None, '--datatype', '-t', help='DataType contains or glob (e.g. "uint8")',
    ),
    unit: Optional[str] = typer.Option(None, '--unit', '-u', help='Unit contains or glob (e.g. "rpm")'),
    source: Optional[str] = typer.Option(
        None, '--source', '-s', help='Source contains or glob (e.g. "App/Fan*")',
    ),
    compact: bool = typer.Option(False, '--compact', '-c', help='One line per parameter: Name=Value'),
    table: bool = typer.Option(
        False, '--table', '-T', help='Aligned table view (default; kept for backward compatibility)',
    ),
    detail: bool = typer.Option(
        False, '--detail', '-v', help='Show the old multi-line detailed view instead of the table',
    ),
):
    """Search parameters by description, datatype, unit, source, or name.

    \b
    All filters are AND-ed. Plain strings match as substrings;
    * and ? work as wildcards.

    \b
    Examples:
      caldb search -D "derate"
      caldb search -D "*temp*" -t uint8
      caldb search -s "App/FanCtl"
      caldb search -u "rpm" -T
    """
    if not any([name, description, datatype, unit, source]):
        raise typer.BadParameter("Provide at least one filter (-n, -D, -t, -u, -s).")
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    rows = db.search_parameters(
        name=name, description=description,
        datatype=datatype, unit=unit, source=source,
    )
    db.close()

    if not rows:
        click.echo("No parameters match the given filters.")
        return

    _print_param_rows(rows, compact, table=not detail)


@app.command()
def tag(
    ctx: typer.Context,
    name: str = typer.Option(..., '--name', '-n', help='Tag name (e.g. v1.2, sprint-5)'),
    message: str = typer.Option('', '--message', '-m', help='Short description of this snapshot'),
    at: Optional[str] = typer.Option(
        None, '--at', metavar='DATETIME', help='Backdate tag to this point, e.g. "2026-06-08 14:06:47"',
    ),
):
    """Create a named snapshot tag at the current point in history.

    Use --at to place the tag at a historical datetime (e.g. from 'caldb changes -c').

    \b
    Examples:
      caldb tag -n v1.2 -m "sprint 5 release candidate"
      caldb tag -n pre-tuning
      caldb tag -n v12.3 --at "2026-06-08 14:06:47"
    """
    db_path = _resolve_db(ctx.obj['db'])
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    if at:
        # Normalise "YYYY-MM-DD HH:MM:SS" -> ISO with T separator for storage
        at_iso = at.strip().replace(' ', 'T')
        db.tag_snapshot(name, message, at=at_iso)
    else:
        db.tag_snapshot(name, message)
    db.close()


@app.command()
def tags(ctx: typer.Context):
    """List all snapshot tags."""
    db_path = _resolve_db(ctx.obj['db'])
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    tag_list = db.list_tags()
    db.close()

    if not tag_list:
        click.echo("No tags yet.  Create one with: caldb tag -n <name>")
        return

    click.echo(f"{len(tag_list)} tag(s):\n")
    for t in tag_list:
        ts = t['ChangeDateTime'][:19].replace('T', ' ')
        cmt = f"  {t['comment']}" if t['comment'] else ''
        click.echo(f"  {ts}  {t['name']}{cmt}")


@app.command()
def restore(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(
        None, '--name', '-n',
        help='Parameter name or glob pattern (omit to restore all parameters at --at tag)',
    ),
    at: Optional[str] = typer.Option(
        None, '--at', metavar='TAG', help='Restore to values as they were at this tag (see: caldb tags)',
    ),
    comment: str = typer.Option(
        '', '--comment', '-c', help='Comment stored with each restore history entry',
    ),
    dry_run: bool = typer.Option(False, '--dry-run', help='Show what would change without writing'),
):
    """Revert parameter values to a previous state.

    \b
    Examples:
      caldb restore -n TempCtlSetPnt           # revert to value before last change
      caldb restore -n TempCtlSetPnt --at v1.2 # revert one param to a tag
      caldb restore --at v1.2                  # revert all params to a tag
      caldb restore --at v1.2 -n "FanSpd*"    # revert matching params to a tag
      caldb restore --at v1.2 --dry-run        # preview without writing

    Each restore is recorded as a 'restore' history entry so the rollback
    is fully traceable in 'caldb log' and 'caldb changes'.
    """
    if not at and not name:
        raise typer.BadParameter("Provide --name (-n) and/or --at <tag>.")
    if not at and name and ('*' in name or '?' in name):
        raise typer.BadParameter("Glob patterns require --at <tag>.")

    db_path = _resolve_db(ctx.obj['db'])
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])

    if at:
        tag_time, diff = db.compute_restore_diff(at, pattern=name)
        if tag_time is None:
            click.echo(f"Tag '{at}' not found.  Use 'caldb tags' to list available tags.")
            db.close()
            return
        if not diff:
            click.echo(f"All parameters already match tag '{at}' -- nothing to restore.")
            db.close()
            return

        ts = tag_time[:19].replace('T', ' ')
        tag = '[DRY RUN] ' if dry_run else ''
        click.echo(
            f"{tag}Restore to tag '{at}'  ({ts}):  "
            f"{len(diff)} parameter(s) would change\n"
        )

        if dry_run or ctx.obj['test']:
            for item in diff:
                click.echo(f"  ~ {item['name']}:  {item['current']}  ->  {item['target']}")
            db.close()
            return

        accepted = set()
        accept_all = False
        click.echo("Confirm each restore  (y=yes  n=skip  a=accept all  q=quit):\n")
        for item in diff:
            if accept_all:
                accepted.add(item['name'])
                continue
            click.echo(f"  {item['name']}:  {item['current']}  ->  {item['target']}")
            raw = click.prompt("  ", default='y', show_default=False,
                               prompt_suffix='[y/n/a/q] > ').strip().lower()
            if raw == 'q':
                break
            if raw == 'a':
                accept_all = True
                accepted.add(item['name'])
            elif raw in ('y', ''):
                accepted.add(item['name'])

        if not accepted:
            click.echo("Nothing accepted -- no changes made.")
            db.close()
            return

        restore_msg = comment or f"restore to tag '{at}'"
        count = 0
        for item in diff:
            if item['name'] not in accepted:
                continue
            ok = db.restore_parameter(
                item['name'], item['target'],
                to_comment=item['target_comment'],
                restore_comment=restore_msg,
            )
            if ok:
                click.echo(f"  Restored: {item['name']}  {item['current']} -> {item['target']}")
                count += 1

        click.echo(f"\n{count} parameter(s) restored.")

    else:
        # Single parameter, no tag -- revert to value before last change
        entries = db.get_parameter_log(name, limit=1)
        if not entries or entries[0].get('OldValue') is None:
            click.echo(f"No previous value to restore for '{name}'.")
            db.close()
            return

        prev_value = entries[0]['OldValue']
        current_rows = db.get_parameters(name)
        current_value = current_rows[0]['Value'] if current_rows else '?'

        if dry_run or ctx.obj['test']:
            click.echo(f"Would restore: {name}  {current_value}  ->  {prev_value}")
            db.close()
            return

        restore_msg = comment or 'restore to previous value'
        ok = db.restore_to_previous(name, restore_comment=restore_msg)
        if ok:
            click.echo(f"Restored: {name}  {current_value} -> {prev_value}")
        else:
            click.echo(f"Nothing to restore for '{name}'.")

    db.close()


@app.command()
def log(
    ctx: typer.Context,
    name: str = typer.Argument(..., help='Parameter name'),
    limit: int = typer.Option(20, '--limit', '-l', show_default=True, help='Max entries to show (0 = all)'),
    table: bool = typer.Option(
        False, '--table', '-T', help='Aligned table view (default; kept for backward compatibility)',
    ),
    detail: bool = typer.Option(
        False, '--detail', '-v', help='Show the old multi-line detailed view instead of the table',
    ),
):
    """Show change history for a parameter."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    entries = db.get_parameter_log(name, limit=limit)
    db.close()
    if not entries:
        click.echo(f"No history found for '{name}'.")
        return

    click.echo(f"History for '{name}' ({len(entries)} entries):\n")

    if not detail:
        _print_changes_table(entries)
        return

    for e in entries:
        ts = e['ChangeDateTime'][:19].replace('T', ' ')
        ctype = e['ChangeType'].upper()
        sc = f"  [{e['SyncComment']}]" if e['SyncComment'] else ''
        click.echo(f"  {ts}  {ctype}{sc}")
        if ctype in ('UPDATE', 'RESTORE'):
            click.echo(f"    value:   {e['OldValue']}  ->  {e['NewValue']}")
            if (e['OldComment'] or '') != (e['NewComment'] or ''):
                click.echo(f"    comment: {e['OldComment']}  ->  {e['NewComment']}")
        elif ctype == 'ADD':
            click.echo(f"    value:   {e['NewValue']}")
        elif ctype == 'DELETE':
            click.echo(f"    value at deletion: {e['OldValue']}")
        elif ctype == 'META':
            click.echo(f"    meta:    {e['NewValue']}")


@app.command()
def status(
    ctx: typer.Context,
    file: Optional[str] = typer.Option(None, '--file', '-f', help='CSV file (auto-detected if omitted)'),
):
    """Show sync status between DB and CSV.

    \b
    Exit codes:
      0  in sync
      1  CSV changed since last sync  (run: caldb sync)
      2  DB changed via CLI since last sync  (run: caldb sync --to-csv)
      3  both changed -- conflict
      4  never synced
    """
    db_path, csv_path = _resolve_pair(ctx.obj['db'], file)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    csv_in_sync, last_sync_time = db.get_sync_status(csv_path)
    db_changed_time = db.get_db_changed_time()
    db.close()

    ts = last_sync_time[:19].replace('T', ' ') if last_sync_time else None

    if ts is None and csv_in_sync is None:
        click.echo("Never synced -- run 'caldb sync' to initialise.")
        ctx.exit(4)

    csv_changed = csv_in_sync is False
    db_changed  = db_changed_time is not None

    if not csv_changed and not db_changed:
        click.echo(f"In sync  (last sync: {ts})")
        exit_code = 0
    elif csv_changed and not db_changed:
        click.echo(f"CSV changed since last sync ({ts}) -- run 'caldb sync'")
        exit_code = 1
    elif not csv_changed and db_changed:
        dts = db_changed_time[:19].replace('T', ' ')
        click.echo(f"DB changed via CLI ({dts}) -- run 'caldb sync --to-csv'")
        exit_code = 2
    else:
        click.echo(
            f"Both CSV and DB changed since last sync ({ts}) -- conflict\n"
            f"  Run 'caldb diff' to see what differs on each side, then:\n"
            f"  caldb sync           to accept CSV values (overwrites CLI edits)\n"
            f"  caldb sync --to-csv  to accept DB values  (overwrites CSV edits)"
        )
        exit_code = 3

    _GIT_LABELS = {
        'modified':  'modified (not staged)',
        'staged':    'staged for commit',
        'both':      'modified and staged',
        'untracked': 'untracked',
    }
    for label, fpath in [('CSV', csv_path), ('DB ', db_path)]:
        st = _git_file_status(fpath)
        if st and st != 'clean':
            click.echo(f"{label} git:  {_GIT_LABELS.get(st, st)}")

    ctx.exit(exit_code)


@app.command()
def diff(
    ctx: typer.Context,
    file: List[str] = typer.Option(
        [], '--file', '-f',
        help='CSV file (auto-detected if omitted). Give -f twice to compare two CSVs directly, no DB.',
    ),
    from_ref: Optional[str] = typer.Option(
        None, '--from', metavar='REF',
        help='Baseline snapshot: tag name, date, or sync comment. Enables tag/date comparison mode.',
    ),
    to_ref: Optional[str] = typer.Option(
        None, '--to', metavar='REF',
        help='Snapshot to compare to (tag/date/sync comment). Default: current DB state. Requires --from.',
    ),
    name: Optional[str] = typer.Option(
        None, '--name', '-n', help='Filter by name or glob pattern (e.g. "FanSpd*")',
    ),
    table: bool = typer.Option(False, '--table', '-T', help='Aligned table view (one row per parameter)'),
):
    """Show what differs between two snapshots of the calibration data.

    \b
    Default (no --from/--to, at most one -f): current CSV vs current DB.
    Useful when 'caldb status' reports a conflict (both sides changed).

    \b
    Extended modes:
      caldb diff -f baseline.csv -f current.csv      -- two CSV files, no DB
      caldb diff --from v1.0 --to v1.2               -- between two tags
      caldb diff --from v1.0                         -- a tag vs current state
      caldb diff --from 2026-06-01 --to 2026-06-10   -- between two dates
    --from/--to also accept a sync comment (see 'caldb changes --since').

    \b
    To resolve a CSV/DB conflict after reviewing (default mode only):
      caldb sync           -- accept CSV values (overwrites CLI edits in DB)
      caldb sync --to-csv  -- accept DB values  (overwrites CSV edits)
    """
    if to_ref and not from_ref:
        raise typer.BadParameter("--to requires --from.")
    if len(file) > 2:
        raise typer.BadParameter("At most two --file/-f values are allowed.")
    if len(file) == 2 and from_ref:
        raise typer.BadParameter("--from/--to cannot be combined with two --file values.")

    if len(file) == 2:
        # CSV-vs-CSV: no DB involved
        old_label, new_label = os.path.basename(file[0]), os.path.basename(file[1])
        d = CalibrationDatabase.compute_snapshot_diff(
            _load_csv_params(file[0]), _load_csv_params(file[1])
        )
        changed = d['changed']
        old_only = [{'name': p['name'], 'value': p['old_value']} for p in d['deleted']]
        new_only = [{'name': p['name'], 'value': p['value']} for p in d['added']]
        meta_only = [{'name': m['name'], 'detail': m['detail']} for m in d['meta_only']]
    elif from_ref:
        # Tag/date/sync-comment vs tag/date/sync-comment (or current state)
        db_path = _resolve_db(ctx.obj['db'])
        db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
        old_time, old_rows = db.get_parameters_at_ref(from_ref)
        if old_rows is None:
            db.close()
            raise typer.BadParameter(
                f"'{from_ref}' did not resolve to a tag, date, or sync comment. "
                f"Use 'caldb tags' to list available tags."
            )
        if to_ref:
            new_time, new_rows = db.get_parameters_at_ref(to_ref)
            if new_rows is None:
                db.close()
                raise typer.BadParameter(
                    f"'{to_ref}' did not resolve to a tag, date, or sync comment. "
                    f"Use 'caldb tags' to list available tags."
                )
            new_params = {r['Name']: r for r in new_rows}
            new_label = to_ref
        else:
            new_time = None  # through the present
            new_params = db._get_all_active()
            new_label = 'current state'
        old_label = from_ref
        old_params = {r['Name']: r for r in old_rows}
        d = CalibrationDatabase.compute_snapshot_diff(old_params, new_params)
        changed = d['changed']
        old_only = [{'name': p['name'], 'value': p['old_value']} for p in d['deleted']]
        new_only = [{'name': p['name'], 'value': p['value']} for p in d['added']]

        # Metadata isn't reconstructed per-snapshot (see get_meta_changes_between),
        # so detect metadata-only changes from the 'meta' history rows in the window
        # instead of compute_snapshot_diff's (structurally blind, here) meta_only.
        already_covered = {r['name'] for r in changed + old_only + new_only}
        meta_only = [
            m for m in db.get_meta_changes_between(old_time, new_time)
            if m['name'] not in already_covered
        ]
        db.close()
    else:
        # Default: current CSV vs current DB
        old_label, new_label = 'DB', 'CSV'
        db_path, csv_path = _resolve_pair(ctx.obj['db'], file[0] if file else None)
        db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
        d = db.compute_diff(csv_path)
        db.close()
        changed = d['changed']
        old_only = [{'name': p['name'], 'value': p['old_value']} for p in d['deleted']]
        new_only = [{'name': p.name, 'value': p.value} for p in d['added']]
        meta_only = [
            {'name': m['name'], 'detail': _format_meta_diff(m['param'], m['db_row'])}
            for m in d['meta_only']
        ]

    if name:
        import fnmatch
        pat = name if ('*' in name or '?' in name) else f'*{name}*'
        changed   = [c for c in changed    if fnmatch.fnmatch(c['name'], pat)]
        old_only  = [p for p in old_only   if fnmatch.fnmatch(p['name'], pat)]
        new_only  = [p for p in new_only   if fnmatch.fnmatch(p['name'], pat)]
        meta_only = [m for m in meta_only  if fnmatch.fnmatch(m['name'], pat)]

    if not changed and not old_only and not new_only and not meta_only:
        click.echo("No differences.")
        return

    if table:
        _print_diff_table(changed, old_only, new_only, meta_only, old_label, new_label)
        click.echo()
    else:
        if changed:
            click.echo(f"VALUE DIFFERS  ({len(changed)} parameter(s)):\n")
            for c in changed:
                click.echo(f"  {c['name']}")
                click.echo(f"    {old_label}:   {c['old_value']}")
                click.echo(f"    {new_label}:  {c['new_value']}")
                if (c['old_comment'] or '') != (c['new_comment'] or ''):
                    click.echo(f"    {old_label} comment:   {c['old_comment']}")
                    click.echo(f"    {new_label} comment:  {c['new_comment']}")
            click.echo()

        if meta_only:
            click.echo(f"METADATA CHANGED  ({len(meta_only)} parameter(s), value unchanged):\n")
            for m in meta_only:
                click.echo(f"  {m['name']}")
                click.echo(f"    {m['detail']}")
            click.echo()

        if old_only:
            click.echo(f"{old_label} ONLY  ({len(old_only)} parameter(s) -- not in {new_label}):\n")
            for p in old_only:
                click.echo(f"  + {p['name']}  ({p['value']})")
            click.echo()

        if new_only:
            click.echo(f"{new_label} ONLY  ({len(new_only)} parameter(s) -- not in {old_label}):\n")
            for p in new_only:
                click.echo(f"  + {p['name']}  ({p['value']})")
            click.echo()

    total = len(changed) + len(old_only) + len(new_only) + len(meta_only)
    click.echo(
        f"Summary: {len(changed)} value conflicts, {len(meta_only)} metadata-only, "
        f"{len(new_only)} {new_label}-only, {len(old_only)} {old_label}-only  "
        f"({total} total differences)"
    )


def _format_change_compact(e):
    ts    = e['ChangeDateTime'][:19].replace('T', ' ')
    ctype = e['ChangeType'].upper()
    sc    = f"  [{e['SyncComment']}]" if e['SyncComment'] else ''
    if ctype in ('UPDATE', 'RESTORE'):
        detail = f"  {e['OldValue']} -> {e['NewValue']}"
    elif ctype in ('ADD', 'META'):
        detail = f"  {e['NewValue']}"
    else:
        detail = ''
    return f"{ts}  {ctype:6s}  {e['Name']}{detail}{sc}"


def _trunc(val, width=22):
    s = str(val) if val is not None else ''
    return s if len(s) <= width else s[:width - 1] + '~'


def _print_table(columns, rows, row_style=None, indent=''):
    """Render rows as a colorized table (rich).  Generic across commands.

    columns:   [(key, header), ...] -- header text and the row dict key it reads
    rows:      [dict, ...]
    row_style: optional callable(row) -> rich style string (e.g. 'green'),
               applied to the whole row; return None/'' for no styling
    indent:    prefix string (e.g. '  ') to left-pad the whole table
    """
    t = Table(box=box.SIMPLE, header_style='bold', show_edge=False, pad_edge=False)
    for _, header in columns:
        t.add_column(header, no_wrap=True, overflow='crop')
    for r in rows:
        cells = [str(r.get(key, '') or '') for key, _ in columns]
        t.add_row(*cells, style=(row_style(r) if row_style else None))

    if indent:
        with _console.capture() as capture:
            _console.print(t)
        for line in capture.get().splitlines():
            click.echo(indent + line)
    else:
        _console.print(t)


_CHANGE_ROW_COLORS = {'ADD': 'green', 'DELETE': 'red', 'UPDATE': 'yellow', 'RESTORE': 'cyan', 'META': 'magenta'}


def _print_diff_table(changed, old_only, new_only, meta_only, old_label, new_label):
    """Render a diff's changed/old_only/new_only/meta_only lists as one colorized
    table, reusing the same Type vocabulary and colors as `caldb changes`."""
    _MAX_VAL = 22
    _MAX_DETAIL = 60

    rows = []
    for c in changed:
        rows.append({
            'type': 'UPDATE', 'name': c['name'],
            'old': _trunc(c['old_value'], _MAX_VAL), 'new': _trunc(c['new_value'], _MAX_VAL),
        })
    for p in old_only:
        rows.append({'type': 'DELETE', 'name': p['name'], 'old': _trunc(p['value'], _MAX_VAL), 'new': ''})
    for p in new_only:
        rows.append({'type': 'ADD', 'name': p['name'], 'old': '', 'new': _trunc(p['value'], _MAX_VAL)})
    for m in meta_only:
        rows.append({'type': 'META', 'name': m['name'], 'old': '', 'new': _trunc(m['detail'], _MAX_DETAIL)})

    _print_table(
        [('type', 'Type'), ('name', 'Name'), ('old', old_label), ('new', new_label)],
        rows,
        row_style=lambda r: _CHANGE_ROW_COLORS.get(r['type']),
    )


def _print_changes_table(entries, indent=''):
    """Print entries as a colorized table."""
    _MAX_VAL = 22

    rows = []
    for e in entries:
        ctype = e['ChangeType'].upper()
        if ctype in ('UPDATE', 'RESTORE'):
            old_v = _trunc(e['OldValue'], _MAX_VAL)
            new_v = _trunc(e['NewValue'], _MAX_VAL)
        elif ctype in ('ADD', 'META'):
            old_v, new_v = '', _trunc(e['NewValue'], _MAX_VAL)
        else:  # DELETE
            old_v, new_v = _trunc(e['OldValue'], _MAX_VAL), ''
        rows.append({
            'ts':    e['ChangeDateTime'][:19].replace('T', ' '),
            'type':  ctype,
            'name':  e['Name'],
            'old':   old_v,
            'new':   new_v,
            'sc':    e['SyncComment'] or '',
        })

    columns = [('ts', 'DateTime'), ('type', 'Type'), ('name', 'Name'),
               ('old', 'Old Value'), ('new', 'New Value')]
    if any(r['sc'] for r in rows):
        columns.append(('sc', 'Comment'))

    _print_table(columns, rows, row_style=lambda r: _CHANGE_ROW_COLORS.get(r['type']), indent=indent)


def _emit_tags_between(tags_desc, after_dt, until_dt):
    """Print tag markers for tags whose timestamp falls in (until_dt, after_dt].

    tags_desc is a list of tag dicts sorted newest-first; consumed in-place
    by popping from the front while tags fall in the window.
    after_dt  -- upper bound (inclusive); None means no upper bound
    until_dt  -- lower bound (exclusive); None means no lower bound
    """
    while tags_desc:
        tag_dt = tags_desc[0]['ChangeDateTime']
        in_window = (
            (after_dt is None or tag_dt <= after_dt) and
            (until_dt is None or tag_dt > until_dt)
        )
        if not in_window:
            break
        t = tags_desc.pop(0)
        label = t['comment'] if t['comment'] else ''
        suffix = f'  "{label}"' if label else ''
        click.secho(f"  (tag: {t['name']}{suffix})", fg='cyan')


@app.command()
def changes(
    ctx: typer.Context,
    count: Optional[int] = typer.Option(
        None, '-n', '--count',
        help='Number of entries to show (0 = all; default: 10, or all with --by-tag)',
    ),
    change_type: Optional[ChangeType] = typer.Option(
        None, '--type', '-t', help='Filter by change type', case_sensitive=False,
    ),
    since: Optional[str] = typer.Option(
        None, '--since', '-s', help='Show changes on or after a date (2026-06-01) or sync comment',
    ),
    compact: bool = typer.Option(False, '--compact', '-c', help='One line per change'),
    table: bool = typer.Option(
        False, '--table', '-T', help='Aligned table view (default; kept for backward compatibility)',
    ),
    detail: bool = typer.Option(
        False, '--detail', '-v', help='Show the old multi-line detailed view instead of the table',
    ),
    no_tags: bool = typer.Option(False, '--no-tags', help='Hide tag markers'),
    by_tag: bool = typer.Option(
        False, '--by-tag', help='Group changes between tag milestones (implies -n 0)',
    ),
):
    """Show recent changes across all parameters.

    Tags are shown as markers interleaved with changes (like git log --oneline).
    Use --by-tag to group changes between tag milestones.

    \b
    Examples:
      caldb changes              # last 10
      caldb changes -n 25        # last 25
      caldb changes -n 0         # all
      caldb changes -t update    # only value changes
      caldb changes -s 2026-06-01
      caldb changes -s "sprint 4 tuning"
      caldb changes -c           # compact, one line per change
      caldb changes -T           # aligned table
      caldb changes --by-tag     # grouped by tag milestones
      caldb changes --by-tag -T  # table per tag section
    """
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    effective_count = count if count is not None else (0 if by_tag else 10)
    entries = db.get_recent_changes(limit=effective_count, since=since)
    tags = db.list_tags()   # oldest first
    db.close()

    if since and not entries:
        click.echo(f"No changes found matching --since '{since}'.")
        return

    if change_type:
        entries = [e for e in entries if e['ChangeType'].lower() == change_type.lower()]

    if not entries:
        click.echo("No changes recorded yet.")
        return

    # ------------------------------------------------------------------
    # --by-tag: group changes between consecutive tag boundaries
    # ------------------------------------------------------------------
    if by_tag:
        if not tags:
            click.echo("No tags found -- create one with 'caldb tag -n <name>'.")
            click.echo()

        # Build sections newest -> oldest:
        #   (header, upper_dt, lower_dt)
        # Changes in section: lower_dt < change.dt <= upper_dt
        # (None upper = no upper bound; None lower = no lower bound)
        sections = []
        tags_desc = list(reversed(tags))   # newest first
        if tags_desc:
            sections.append((
                f"After {tags_desc[0]['name']}:",
                None,
                tags_desc[0]['ChangeDateTime'],
            ))
            for i in range(len(tags_desc) - 1):
                newer, older = tags_desc[i], tags_desc[i + 1]
                label = f'  "{newer["comment"]}"' if newer['comment'] else ''
                sections.append((
                    f"{older['name']}..{newer['name']}{label}:",
                    newer['ChangeDateTime'],
                    older['ChangeDateTime'],
                ))
            oldest = tags_desc[-1]
            label = f'  "{oldest["comment"]}"' if oldest['comment'] else ''
            sections.append((
                f"Before {oldest['name']}{label}:",
                oldest['ChangeDateTime'],
                None,
            ))
        else:
            sections.append(("All changes (no tags):", None, None))

        for header, upper_dt, lower_dt in sections:
            section_entries = [
                e for e in entries
                if (upper_dt is None or e['ChangeDateTime'] <= upper_dt)
                and (lower_dt is None or e['ChangeDateTime'] > lower_dt)
            ]
            if not section_entries:
                continue
            click.secho(header, fg='cyan')
            if not detail:
                _print_changes_table(section_entries, indent='  ')
            else:
                for e in section_entries:
                    click.echo(f"  {_format_change_compact(e)}")
            click.echo()
        return

    # ------------------------------------------------------------------
    # Standard interleaved view
    # ------------------------------------------------------------------

    # Table is the default view; --detail falls through to the compact/detailed logic below.
    if not detail:
        _print_changes_table(entries)
        return

    tags_desc = list(reversed(tags)) if not no_tags else []

    # Emit any tags newer than the first (most recent) change entry
    if tags_desc:
        _emit_tags_between(tags_desc, after_dt=None, until_dt=entries[0]['ChangeDateTime'])

    if compact:
        for i, e in enumerate(entries):
            click.echo(_format_change_compact(e))
            next_dt = entries[i + 1]['ChangeDateTime'] if i + 1 < len(entries) else None
            _emit_tags_between(tags_desc, after_dt=e['ChangeDateTime'], until_dt=next_dt)
        return

    label = f"last {effective_count}" if effective_count else "all"
    type_label = f" [{change_type.value}]" if change_type else ""
    click.echo(f"{len(entries)} change(s){type_label} ({label}):\n")

    for i, e in enumerate(entries):
        ts = e['ChangeDateTime'][:19].replace('T', ' ')
        ctype = e['ChangeType'].upper()
        sc = f"  [{e['SyncComment']}]" if e['SyncComment'] else ''
        click.echo(f"  {ts}  {ctype:6s}  {e['Name']}{sc}")
        if ctype in ('UPDATE', 'RESTORE'):
            click.echo(f"           value:   {e['OldValue']}  ->  {e['NewValue']}")
            if (e['OldComment'] or '') != (e['NewComment'] or ''):
                click.echo(f"           comment: {e['OldComment']}  ->  {e['NewComment']}")
        elif ctype == 'ADD':
            click.echo(f"           value:   {e['NewValue']}")
        elif ctype == 'DELETE':
            click.echo(f"           value at deletion: {e['OldValue']}")
        elif ctype == 'META':
            click.echo(f"           meta:    {e['NewValue']}")
        next_dt = entries[i + 1]['ChangeDateTime'] if i + 1 < len(entries) else None
        _emit_tags_between(tags_desc, after_dt=e['ChangeDateTime'], until_dt=next_dt)


@app.command()
def annotate(
    ctx: typer.Context,
    message: Optional[str] = typer.Option(
        None, '--message', '-m', help='New sync comment (omit to enter interactive mode)',
    ),
    since: Optional[str] = typer.Option(
        None, '--since', '-s', help='Start of time window (ISO date/datetime, e.g. "2026-06-08 14:10")',
    ),
    until: Optional[str] = typer.Option(
        None, '--until', '-u',
        help='End of time window, exclusive. Omit to cover everything from --since onward.',
    ),
    entry_id: Optional[int] = typer.Option(
        None, '--id', help='Annotate a single history row by its id (see: caldb log)',
    ),
    count: int = typer.Option(
        20, '-n', '--count', show_default=True, help='Interactive mode: max entries to step through',
    ),
    change_type: Optional[ChangeType] = typer.Option(
        None, '--type', '-t', help='Interactive mode: filter by change type', case_sensitive=False,
    ),
    dry_run: bool = typer.Option(False, '--dry-run', help='Bulk mode: preview matching rows without writing'),
):
    """Retroactively set or update the sync comment on history entries.

    Without --message, opens an interactive session where you step through
    recent changes one by one and edit each comment in place.

    \b
    Interactive mode (no --message):
      caldb annotate                     # step through last 20 changes
      caldb annotate -n 50              # step through last 50
      caldb annotate -s 2026-06-08      # only entries from that date onward
      caldb annotate -t update          # only value changes

    \b
    Bulk mode (with --message):
      caldb annotate -m "sprint 5" -s "2026-06-08 14:10"
      caldb annotate -m "hot fix" -s "2026-06-10 09:00" -u "2026-06-10 10:00"
      caldb annotate -m "typo fix" --id 42
      caldb annotate -m "sprint 5" -s "2026-06-08" --dry-run

    See also: caldb review  -- interactively confirm pending CSV changes before writing
    """
    def _norm_dt(dt):
        if dt and len(dt) > 10 and dt[10] == ' ':
            return dt[:10] + 'T' + dt[11:]
        return dt

    db_path = _resolve_db(ctx.obj['db'])
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])

    # ------------------------------------------------------------------
    # Interactive mode
    # ------------------------------------------------------------------
    if message is None:
        entries = db.get_recent_changes(limit=count, since=since)
        if change_type:
            entries = [e for e in entries if e['ChangeType'].lower() == change_type.lower()]
        # Reverse so we step oldest-first (more natural for labelling a session)
        entries = list(reversed(entries))

        if not entries:
            click.echo("No history entries found.")
            db.close()
            return

        click.echo(
            f"\n{len(entries)} change(s) to annotate\n"
            f"Enter=keep  <text>=set comment  s=skip  q=quit&save  a=abort\n"
        )

        pending = []   # list of (id, new_comment) to write at the end
        total = len(entries)

        for idx, e in enumerate(entries, 1):
            ts = e['ChangeDateTime'][:19].replace('T', ' ')
            ctype = e['ChangeType'].upper()
            existing = e['SyncComment'] or ''

            click.echo(f"--- [{idx}/{total}]  {ctype:7s}  {e['Name']}  ({ts})")

            # Show value context
            if ctype in ('UPDATE', 'RESTORE'):
                click.echo(f"    value:   {e['OldValue']}  ->  {e['NewValue']}")
                if (e.get('OldComment') or '') != (e.get('NewComment') or ''):
                    click.echo(f"    param comment: {e.get('OldComment')}  ->  {e.get('NewComment')}")
            elif ctype == 'ADD':
                click.echo(f"    value:   {e['NewValue']}")
            elif ctype == 'DELETE':
                click.echo(f"    value at deletion: {e['OldValue']}")
            elif ctype == 'META':
                click.echo(f"    meta:    {e['NewValue']}")

            if existing:
                prompt_text = f"    sync comment [{existing}]"
                raw = click.prompt(prompt_text, default=existing,
                                   show_default=False, prompt_suffix=' > ')
            else:
                raw = click.prompt("    sync comment", default='',
                                   show_default=False, prompt_suffix=' > ')
            raw = raw.strip()

            if raw.lower() == 'a':
                click.echo("\nAborted -- nothing written.")
                db.close()
                return
            if raw.lower() == 'q':
                break
            if raw.lower() == 's' or raw == existing:
                continue   # skip: no change
            pending.append((e['id'], raw))

        if not pending:
            click.echo("\nNo changes made.")
            db.close()
            return

        written = db.annotate_many(pending)
        db.close()
        click.echo(f"\nUpdated {written} history row(s).")
        return

    # ------------------------------------------------------------------
    # Bulk mode (--message provided)
    # ------------------------------------------------------------------
    if entry_id is None and since is None:
        raise typer.BadParameter(
            "Provide --since (for a time window) or --id (for one row), "
            "or omit --message to use interactive mode."
        )

    if dry_run:
        cur = db.conn.cursor()
        if entry_id is not None:
            cur.execute(
                'SELECT id, Name, ChangeType, ChangeDateTime, SyncComment '
                'FROM calibration_history WHERE id=?', (entry_id,)
            )
        elif until is not None:
            cur.execute(
                'SELECT id, Name, ChangeType, ChangeDateTime, SyncComment '
                'FROM calibration_history '
                'WHERE ChangeDateTime >= ? AND ChangeDateTime < ? ORDER BY id',
                (_norm_dt(since), _norm_dt(until)),
            )
        else:
            cur.execute(
                'SELECT id, Name, ChangeType, ChangeDateTime, SyncComment '
                'FROM calibration_history '
                'WHERE ChangeDateTime >= ? ORDER BY id',
                (_norm_dt(since),),
            )
        rows = cur.fetchall()
        db.close()
        if not rows:
            click.echo("No matching history rows.")
            return
        click.echo(f"[DRY RUN] Would annotate {len(rows)} row(s) with: \"{message}\"\n")
        for r in rows:
            rid, name, ctype, dt, sc = r
            old = f'  (was: "{sc}")' if sc else ''
            click.echo(f"  {rid:>5}  {dt[:19]}  {ctype:6}  {name}{old}")
        return

    n = db.annotate_changes(message, since=since, until=until, entry_id=entry_id)
    db.close()
    if n == 0:
        click.echo("No matching history rows found.")
    else:
        click.echo(f"Updated {n} history row(s) -> \"{message}\"")


@app.command('install-hook')
def install_hook():
    """Install a git pre-commit hook that auto-syncs DB files for staged CSVs."""
    # Walk up from cwd to find .git directory
    path = os.getcwd()
    while True:
        git_dir = os.path.join(path, '.git')
        if os.path.isdir(git_dir):
            break
        parent = os.path.dirname(path)
        if parent == path:
            raise typer.BadParameter("Not inside a git repository.")
        path = parent

    hooks_dir = os.path.join(git_dir, 'hooks')
    os.makedirs(hooks_dir, exist_ok=True)
    hook_path = os.path.join(hooks_dir, 'pre-commit')

    if os.path.exists(hook_path):
        existing = open(hook_path).read()
        if _HOOK_MARKER_START in existing:
            click.echo("caldb hook is already installed.")
            return
        with open(hook_path, 'a') as f:
            f.write('\n' + _HOOK_BODY)
        click.echo(f"Appended caldb hook to existing {hook_path}")
    else:
        with open(hook_path, 'w') as f:
            f.write('#!/bin/sh\n' + _HOOK_BODY)
        click.echo(f"Created {hook_path}")

    current = os.stat(hook_path).st_mode
    os.chmod(hook_path, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    # click.confirm()/click.prompt() (used in review/sync/annotate/restore) raise the
    # real click.exceptions.Abort on interrupt. typer (this version) vendors its own
    # internal copy of click and only recognizes exceptions from that copy, so a real
    # click.Abort would otherwise propagate as a raw traceback instead of the usual
    # "Aborted!" message -- caught here to match click's own behavior.
    try:
        app()
    except click.exceptions.Abort:
        click.echo('Aborted!', err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
