import argparse
from .cal_db_util import CalibrationDatabase, CalibrationParameter

def main():
    parser = argparse.ArgumentParser(description='Calibration Database CLI')
    parser.add_argument('--db', default='data/calibration.db', help='Database file path')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new parameter')
    add_parser.add_argument('--prefix', default='cal-', help='UID prefix')
    add_parser.add_argument('--name', required=True, help='Parameter name')
    add_parser.add_argument('--value', default=None, help='Parameter value')
    add_parser.add_argument('--comment', default=None, help='Comment')
    add_parser.add_argument('--datatype', default=None, help='Data type')
    add_parser.add_argument('--unit', default=None, help='Unit')
    add_parser.add_argument('--size', default=None, help='Size')
    add_parser.add_argument('--min', type=float, help='Minimum value')
    add_parser.add_argument('--max', type=float, help='Maximum value')
    add_parser.add_argument('--description', default=None, help='Description')
    add_parser.add_argument('--aliases', default=None, help='Aliases (semicolon-separated)')
    add_parser.add_argument('--mod-comment', default=None, help='Modification comment')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update an existing parameter')
    update_parser.add_argument('--name', required=True, help='Parameter name')
    update_parser.add_argument('--value', default=None, help='Parameter value')
    update_parser.add_argument('--mod-comment', default=None, help='Modification comment')

    # Rename command
    rename_parser = subparsers.add_parser('rename', help='Rename a parameter')
    rename_parser.add_argument('--identifier', required=True, help='Parameter MID, UID, or Name')
    rename_parser.add_argument('--new-name', required=True, help='New parameter name')
    rename_parser.add_argument('--mod-comment', default=None, help='Modification comment')

    # Load command
    load_parser = subparsers.add_parser('load', help='Load parameters from file')
    load_parser.add_argument('--file', required=True, help='CSV or JSON file path')
    load_parser.add_argument('--prefix', default='cal-', help='UID prefix')
    load_parser.add_argument('--type', choices=['csv', 'json'], default='csv', help='File type')

    # Export command
    export_parser = subparsers.add_parser('export', help='Export database to CSV')
    export_parser.add_argument('--file', default='data/calibration_export.csv', help='Output CSV file path')

    args = parser.parse_args()
    db = CalibrationDatabase(args.db)

    if args.command == 'add':
        param = CalibrationParameter(
            name=args.name,
            value=args.value,
            comment=args.comment,
            datatype=args.datatype,
            unit=args.unit,
            size=args.size,
            min_val=args.min,
            max_val=args.max,
            description=args.description,
            aliases=args.aliases,
            mod_comment=args.mod_comment
        )
        db.add_parameter(args.prefix, param)

    elif args.command == 'update':
        param = CalibrationParameter(
            name=args.name,
            value=args.value,
            mod_comment=args.mod_comment
        )
        db.update_parameter(param)

    elif args.command == 'rename':
        db.rename_parameter(args.identifier, args.new_name, args.mod_comment)

    elif args.command == 'load':
        if args.type == 'csv':
            db.load_from_csv(args.file, args.prefix)
        else:
            db.load_from_json(args.file, args.prefix)

    elif args.command == 'export':
        db.export_to_csv(args.file)

    db.close()

if __name__ == "__main__":
    main()