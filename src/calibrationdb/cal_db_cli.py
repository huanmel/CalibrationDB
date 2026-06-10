import glob
import os
import stat
import subprocess
import click
from .cal_db_util import CalibrationDatabase, CalibrationParameter

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
        raise click.UsageError(f"Multiple DB files found ({names}). Specify --db.")
    raise click.UsageError("No .db file found. Provide --db <path>.")


def _resolve_pair(db, csv_file):
    """Resolve (db_path, csv_path), deriving each from the other when omitted.

    Priority:
      both given          -> use as-is
      only --db           -> csv = same base name + .csv
      only --file         -> db  = same base name + .db  (must exist)
      neither given       -> scan cwd for a matched .db/.csv pair
    """
    if db and csv_file:
        return db, csv_file

    if db:
        return db, os.path.splitext(db)[0] + '.csv'

    if csv_file:
        db_candidate = os.path.splitext(csv_file)[0] + '.db'
        if not os.path.exists(db_candidate):
            raise click.UsageError(
                f"No matching DB found at '{db_candidate}'. Provide --db."
            )
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
        raise click.UsageError(f"Multiple DB/CSV pairs found ({names}). Specify --db.")
    # No matched pairs — fall back to any single .db
    if len(db_files) == 1:
        click.echo(f"Using DB: {db_files[0]}")
        return db_files[0], os.path.splitext(db_files[0])[0] + '.csv'
    if db_files:
        names = ', '.join(db_files)
        raise click.UsageError(f"Multiple DB files found ({names}). Specify --db.")
    raise click.UsageError("No .db file found. Provide --db <path>.")


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


def _print_sync_report(added, changed, deleted, dry_run=False):
    tag = '[DRY RUN] ' if dry_run else ''
    total = len(added) + len(changed) + len(deleted)
    click.echo(f"{tag}Sync: {len(added)} added, {len(changed)} changed, {len(deleted)} deleted ({total} total)")
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


@click.group()
@click.option('--db', '-d', default=None, help='Database file path')
@click.option('--test', is_flag=True, default=False, help='Dry-run: rollback all changes')
@click.pass_context
def cli(ctx, db, test):
    ctx.ensure_object(dict)
    ctx.obj['db'] = db
    ctx.obj['test'] = test


@cli.command()
@click.option('--name', '-n', required=True, help='Parameter name')
@click.option('--value', '-v', default=None, help='Parameter value')
@click.option('--comment', '-c', default=None, help='Comment')
@click.option('--datatype', default=None, help='Data type (uint8, single, boolean, …)')
@click.option('--unit', '-u', default=None, help='Unit')
@click.option('--size', default=None, help='Array size')
@click.option('--min', 'min_val', type=float, default=None, help='Minimum value')
@click.option('--max', 'max_val', type=float, default=None, help='Maximum value')
@click.option('--description', default=None, help='Description')
@click.option('--aliases', default=None, help='Aliases (semicolon-separated)')
@click.option('--prefix', '-p', default='CAL-', help='UID prefix', show_default=True)
@click.option('--mod-comment', '-m', default=None, help='Modification comment')
@click.pass_context
def add(ctx, name, value, comment, datatype, unit, size, min_val, max_val,
        description, aliases, prefix, mod_comment):
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


@cli.command()
@click.option('--name', '-n', required=True, help='Parameter name')
@click.option('--value', '-v', default=None, help='New value')
@click.option('--mod-comment', '-m', default=None, help='Modification comment')
@click.pass_context
def update(ctx, name, value, mod_comment):
    """Update the value of an existing parameter."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.update_parameter(CalibrationParameter(name=name, value=value, mod_comment=mod_comment))
    db.close()


@cli.command()
@click.option('--identifier', '-i', required=True, help='MID, UID, or Name')
@click.option('--new-name', required=True, help='New parameter name')
@click.option('--mod-comment', '-m', default='', help='Modification comment')
@click.pass_context
def rename(ctx, identifier, new_name, mod_comment):
    """Rename a parameter (old name moves to aliases)."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.rename_parameter(identifier, new_name, mod_comment)
    db.close()


@cli.command()
@click.option('--name', '-n', required=True, help='Parameter name')
@click.option('--comment', '-c', default='', help='Reason for deletion')
@click.pass_context
def delete(ctx, name, comment):
    """Soft-delete a parameter (kept in history)."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.soft_delete(name, comment)
    db.close()


@cli.command()
@click.option('--file', '-f', default=None, help='CSV file to review')
@click.option('--prefix', '-p', default='CAL-', show_default=True)
@click.pass_context
def review(ctx, file, prefix):
    """Interactively review each change before it is written to the DB.

    \b
    For every added, changed, or deleted parameter you can:
      Enter          confirm with no comment
      <any text>     confirm and attach that text as the change comment
      s              skip (do not apply this change)
      q              stop reviewing and apply everything confirmed so far
      a              abort — apply nothing
    """
    db_path, file = _resolve_pair(ctx.obj['db'], file)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    diff = db.compute_diff(file)

    added   = diff['added']
    changed = diff['changed']
    deleted = diff['deleted']
    total   = len(added) + len(changed) + len(deleted)

    if total == 0:
        click.echo("Nothing to review — DB is up to date.")
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

    def _prompt_change(idx, label, detail_lines):
        """Show one change and return (action, comment).
        action: 'confirm' | 'skip' | 'quit' | 'abort'
        """
        click.echo(f"--- [{idx}/{total}]  {label}")
        for line in detail_lines:
            click.echo(f"    {line}")
        raw = click.prompt("    comment", default='', show_default=False,
                           prompt_suffix=' > ')
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
           f"comment:  {_fmt(p.comment)}"])
         for p in added] +
        [('UPDATE', c['name'],
          [f"value:    {_fmt(c['old_value'])}  ->  {_fmt(c['new_value'])}"] +
          ([f"comment:  {_fmt(c['old_comment'])}  ->  {_fmt(c['new_comment'])}"]
           if (c['old_comment'] or '') != (c['new_comment'] or '') else []))
         for c in changed] +
        [('DELETE', d['name'],
          [f"value:    {_fmt(d['old_value'])}",
           f"comment:  {_fmt(d['old_comment'])}"])
         for d in deleted]
    )

    for idx, (ctype, name, details) in enumerate(items, 1):
        action, cmt = _prompt_change(idx, f"{ctype:6s}  {name}", details)
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
        click.echo("Aborted — nothing written.")
        db.close()
        return

    if not confirmed:
        click.echo("Nothing confirmed — nothing written.")
        db.close()
        return

    applied_added, applied_changed, applied_deleted = db.apply_changes(
        diff, prefix=prefix, only=confirmed, per_comments=per_comments,
    )
    db.close()
    _print_sync_report(applied_added, applied_changed, applied_deleted)


@cli.command()
@click.option('--file', '-f', default=None, help='CSV or JSON file path')
@click.option('--prefix', '-p', default='CAL-', show_default=True)
@click.option('--type', 'fmt', type=click.Choice(['csv', 'json']), default=None,
              help='File format (default: inferred from extension)')
@click.pass_context
def load(ctx, file, prefix, fmt):
    """Bulk-load parameters from a CSV or JSON file."""
    db_path, file = _resolve_pair(ctx.obj['db'], file)
    if fmt is None:
        fmt = 'json' if file.lower().endswith('.json') else 'csv'
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    if fmt == 'csv':
        db.load_from_csv(file, prefix)
    else:
        db.load_from_json(file, prefix)
    db.close()


@cli.command()
@click.option('--file', '-f', default=None, help='CSV file to sync from/to')
@click.option('--prefix', '-p', default='CAL-', show_default=True)
@click.option('--comment', '-c', default='', help='Comment stored with all changes (CSV->DB only)')
@click.option('--dry-run', is_flag=True, help='Show what would change without writing')
@click.option('--to-csv', 'to_csv', is_flag=True,
              help='Write DB changes back to CSV instead of the default CSV->DB direction')
@click.pass_context
def sync(ctx, file, prefix, comment, dry_run, to_csv):
    """Sync DB with CSV.

    \b
    Default direction:  CSV -> DB  (record CSV edits in the database)
    Reverse direction:  DB  -> CSV (write CLI edits back to the CSV file)

    Direction is auto-detected when omitted:
      only CSV changed  ->  CSV -> DB
      only DB changed   ->  DB  -> CSV  (same as --to-csv)
      both changed      ->  conflict warning, manual resolution required
    """
    db_path, csv_path = _resolve_pair(ctx.obj['db'], file)
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
                "Both CSV and DB changed since last sync — conflict.\n"
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
                    f"Nothing to write back — {n_del_warn} CSV row(s) not in active DB "
                    f"(soft-deleted or not yet synced)."
                )
            else:
                click.echo("Nothing to write back — CSV matches DB.")
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
                click.echo("\nCSV-only (not in active DB — left as-is):")
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
            click.echo("\nNothing accepted — CSV unchanged.")
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
        added, changed, deleted = db.sync_from_csv(
            csv_path, prefix=prefix, sync_comment=comment, dry_run=dry_run,
        )
        _print_sync_report(added, changed, deleted, dry_run=dry_run)

    db.close()


@cli.command()
@click.option('--file', '-f', default=None, help='Output CSV file path')
@click.pass_context
def export(ctx, file):
    """Export the database to CSV."""
    db_path, file = _resolve_pair(ctx.obj['db'], file)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.export_to_csv(file)
    db.close()


@cli.command()
@click.option('--name', '-n', default=None,
              help='Parameter name or glob pattern. Omit to check all.')
@click.pass_context
def validate(ctx, name):
    """Check parameter values against their Min/Max/DataType/Size constraints."""
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    results = db.validate_parameters(name)
    db.close()

    if not results:
        label = f"matching '{name}'" if name else "all parameters"
        click.echo(f"OK — no constraint violations ({label}).")
        return

    click.echo(f"{len(results)} parameter(s) with violations:\n")
    for r in results:
        click.secho(f"  {r['name']}  ({r['value']})", bold=True)
        for w in r['warnings']:
            click.echo(f"    ! {w}")
    ctx.exit(1)


def _print_param_rows(rows, compact):
    """Shared display logic for show and search."""
    if compact:
        for r in rows:
            click.echo(f"{r['Name']}={r['Value']}")
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


@cli.command()
@click.option('--name', '-n', default=None,
              help='Parameter name or glob pattern (e.g. "FanSpd*"). Omit to show all.')
@click.option('--compact', '-c', is_flag=True, help='One line per parameter: Name=Value')
@click.option('--at', default=None, metavar='TAG',
              help='Show values as they were at a named tag (see: caldb tags)')
@click.pass_context
def show(ctx, name, compact, at):
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

    _print_param_rows(rows, compact)


@cli.command()
@click.option('--name', '-n', default=None,
              help='Name glob pattern (e.g. "*derate*")')
@click.option('--description', '-D', default=None,
              help='Description contains or glob pattern')
@click.option('--datatype', '-t', default=None,
              help='DataType contains or glob (e.g. "uint8")')
@click.option('--unit', '-u', default=None,
              help='Unit contains or glob (e.g. "rpm")')
@click.option('--source', '-s', default=None,
              help='Source contains or glob (e.g. "App/Fan*")')
@click.option('--compact', '-c', is_flag=True, help='One line per parameter: Name=Value')
@click.pass_context
def search(ctx, name, description, datatype, unit, source, compact):
    """Search parameters by description, datatype, unit, source, or name.

    \b
    All filters are AND-ed. Plain strings match as substrings;
    * and ? work as wildcards.

    \b
    Examples:
      caldb search -D "derate"
      caldb search -D "*temp*" -t uint8
      caldb search -s "App/FanCtl"
      caldb search -u "rpm" -c
    """
    if not any([name, description, datatype, unit, source]):
        raise click.UsageError("Provide at least one filter (-n, -D, -t, -u, -s).")
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

    _print_param_rows(rows, compact)


@cli.command()
@click.option('--name', '-n', required=True, help='Tag name (e.g. v1.2, sprint-5)')
@click.option('--message', '-m', default='', help='Short description of this snapshot')
@click.pass_context
def tag(ctx, name, message):
    """Create a named snapshot tag at the current point in history.

    \b
    Examples:
      caldb tag -n v1.2 -m "sprint 5 release candidate"
      caldb tag -n pre-tuning

    Use 'caldb tags' to list tags and 'caldb show --at <tag>' to query them.
    """
    db_path = _resolve_db(ctx.obj['db'])
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    db.tag_snapshot(name, message)
    db.close()


@cli.command()
@click.pass_context
def tags(ctx):
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


@cli.command()
@click.option('--name', '-n', default=None,
              help='Parameter name or glob pattern (omit to restore all parameters at --at tag)')
@click.option('--at', default=None, metavar='TAG',
              help='Restore to values as they were at this tag (see: caldb tags)')
@click.option('--comment', '-c', default='',
              help='Comment stored with each restore history entry')
@click.option('--dry-run', is_flag=True, help='Show what would change without writing')
@click.pass_context
def restore(ctx, name, at, comment, dry_run):
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
        raise click.UsageError("Provide --name (-n) and/or --at <tag>.")
    if not at and name and ('*' in name or '?' in name):
        raise click.UsageError("Glob patterns require --at <tag>.")

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
        # Single parameter, no tag — revert to value before last change
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


@cli.command()
@click.option('--name', '-n', required=True, help='Parameter name')
@click.option('--limit', '-l', default=20, show_default=True, help='Max entries to show')
@click.pass_context
def log(ctx, name, limit):
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


@cli.command()
@click.option('--file', '-f', default=None, help='CSV file (auto-detected if omitted)')
@click.pass_context
def status(ctx, file):
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
        click.echo(f"Both CSV and DB changed since last sync ({ts}) -- conflict, resolve manually")
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


@cli.command()
@click.option('-n', '--count', default=10, show_default=True,
              help='Number of entries to show (0 = all)')
@click.option('--type', '-t', 'change_type',
              type=click.Choice(['add', 'update', 'delete', 'restore'], case_sensitive=False),
              default=None, help='Filter by change type')
@click.option('--since', '-s', default=None,
              help='Show changes on or after a date (2026-06-01) or sync comment')
@click.option('--compact', '-c', is_flag=True, help='One line per change')
@click.pass_context
def changes(ctx, count, change_type, since, compact):
    """Show recent changes across all parameters.

    \b
    Examples:
      caldb changes              # last 10
      caldb changes -n 25        # last 25
      caldb changes -n 0         # all
      caldb changes -t update    # only value changes
      caldb changes -s 2026-06-01
      caldb changes -s "sprint 4 tuning"
      caldb changes -c           # compact, one line per change
    """
    db_path = _resolve_db(ctx.obj['db'])
    _warn_if_unsynced(db_path)
    db = CalibrationDatabase(db_path, test_mode=ctx.obj['test'])
    entries = db.get_recent_changes(limit=count, since=since)
    db.close()

    if since and not entries:
        click.echo(f"No changes found matching --since '{since}'.")
        return

    if change_type:
        entries = [e for e in entries if e['ChangeType'].lower() == change_type.lower()]

    if not entries:
        click.echo("No changes recorded yet.")
        return

    if compact:
        for e in entries:
            ts = e['ChangeDateTime'][:19].replace('T', ' ')
            ctype = e['ChangeType'].upper()
            sc = f"  [{e['SyncComment']}]" if e['SyncComment'] else ''
            if ctype in ('UPDATE', 'RESTORE'):
                detail = f"  {e['OldValue']} -> {e['NewValue']}"
            elif ctype == 'ADD':
                detail = f"  {e['NewValue']}"
            else:
                detail = ''
            click.echo(f"{ts}  {ctype:6s}  {e['Name']}{detail}{sc}")
        return

    label = f"last {count}" if count else "all"
    type_label = f" [{change_type}]" if change_type else ""
    click.echo(f"{len(entries)} change(s){type_label} ({label}):\n")

    for e in entries:
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


@cli.command('install-hook')
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
            raise click.UsageError("Not inside a git repository.")
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
    cli()


if __name__ == "__main__":
    main()
