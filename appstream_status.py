import argparse
import sqlite3
import json
from datetime import datetime
from dateutil import parser as date_parser
from pathlib import Path

# Tables to check
TABLES = [
    "rhel8_main", "rhel8_full", "rhel8_rolling", "rhel8_dependent",
    "rhel9_main", "rhel9_full", "rhel9_rolling", "rhel9_dependent"
]

RETIRE_COLS = ["Retirement Date", "End of Life", "End Date"]
NAME_COLS = ["Application Stream", "Application", "Component"]


def parse_args():
    parser = argparse.ArgumentParser(description="Query RHEL AppStreams lifecycle status.")
    parser.add_argument(
        "--date", type=str, default=datetime.today().strftime("%Y-%m-%d"),
        help="Reference date in YYYY-MM-DD format (default: today)"
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--db", type=str, default=None,
        help="Path to the SQLite database file"
    )
    source_group.add_argument(
        "--json", type=str, default=None,
        help="Path to the JSON data file"
    )

    parser.add_argument(
        "--show-supported", action="store_true",
        help="Show details about supported packages"
    )
    parser.add_argument(
        "--show-expired", action="store_true",
        help="Show details about retired packages"
    )
    return parser.parse_args()


def parse_date(date_str):
    try:
        return date_parser.parse(date_str).date()
    except Exception:
        return None


def find_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


# ---------------------------------------------------------------------------
# SQLite data source
# ---------------------------------------------------------------------------
def query_table_sqlite(cursor, table, ref_date):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]

    retire_col = find_column(columns, RETIRE_COLS)
    name_col = find_column(columns, NAME_COLS)
    if not retire_col or not name_col:
        print(f"⚠ Skipping {table}: Missing expected column(s).")
        return [], []

    cursor.execute(f"SELECT rowid, * FROM {table}")
    rows = cursor.fetchall()
    col_names = [desc[0] for desc in cursor.description]

    supported = []
    expired = []

    for row in rows:
        row_dict = dict(zip(col_names, row))
        retire_raw = row_dict.get(retire_col, "")
        retire_date = parse_date(retire_raw)
        if not retire_date:
            continue

        delta_days = (retire_date - ref_date).days
        row_dict["Days Remaining"] = delta_days
        row_dict["_retire_col"] = retire_col
        row_dict["_name_col"] = name_col
        row_dict["_retire_date"] = retire_date

        if delta_days < 0:
            expired.append(row_dict)
        else:
            supported.append(row_dict)

    return supported, expired


# ---------------------------------------------------------------------------
# JSON data source
# ---------------------------------------------------------------------------
def query_table_json(table_data, table_name, ref_date):
    columns = table_data.get("columns", [])
    rows = table_data.get("rows", [])

    retire_col = find_column(columns, RETIRE_COLS)
    name_col = find_column(columns, NAME_COLS)
    if not retire_col or not name_col:
        print(f"⚠ Skipping {table_name}: Missing expected column(s).")
        return [], []

    supported = []
    expired = []

    for row in rows:
        retire_raw = row.get(retire_col, "")
        retire_date = parse_date(retire_raw)
        if not retire_date:
            continue

        delta_days = (retire_date - ref_date).days
        entry = dict(row)
        entry["Days Remaining"] = delta_days
        entry["_retire_col"] = retire_col
        entry["_name_col"] = name_col
        entry["_retire_date"] = retire_date

        if delta_days < 0:
            expired.append(entry)
        else:
            supported.append(entry)

    return supported, expired


def print_package_details(title, entries, is_expired):
    sorted_entries = sorted(entries, key=lambda x: x.get(x["_name_col"], "").lower())
    print(f"  {title}")
    for entry in sorted_entries:
        name = entry.get(entry["_name_col"], "Unknown")
        retire = entry.get(entry["_retire_col"], "")
        delta = abs(entry.get("Days Remaining", 0))
        if is_expired:
            print(f"    - {name:40} → retired on {retire} ({delta} days ago)")
        else:
            print(f"    - {name:40} → retires on {retire} ({delta} days left)")


def resolve_data_source(args):
    """Determine the data source: --db, --json, or auto-detect."""
    if args.db:
        return "sqlite", args.db
    if args.json:
        return "json", args.json

    # Auto-detect: prefer JSON if present, fall back to SQLite
    json_path = Path("rhel_app_streams.json")
    db_path = Path("rhel_app_streams.db")

    if json_path.exists():
        return "json", str(json_path)
    if db_path.exists():
        return "sqlite", str(db_path)

    print("❌ No data source found. Provide --db or --json, or run fetch_rhel_appstreams.py first.")
    return None, None


def main():
    args = parse_args()

    ref_date = parse_date(args.date)
    if not ref_date:
        print("❌ Invalid date format. Use YYYY-MM-DD.")
        return

    source_type, source_path = resolve_data_source(args)
    if not source_type:
        return

    source_file = Path(source_path)
    if not source_file.exists():
        print(f"❌ Data source not found: {source_file}")
        return

    print(f"📅 Reference date: {ref_date}")
    print(f"📂 Data source:    {source_file} ({source_type})\n")

    # --- SQLite path ---
    if source_type == "sqlite":
        conn = sqlite3.connect(str(source_file))
        cursor = conn.cursor()

        for table in TABLES:
            print(f"🔎 Table: {table}")
            supported, expired = query_table_sqlite(cursor, table, ref_date)
            print(f"  ✅ Supported: {len(supported)}")
            print(f"  ❌ Expired:   {len(expired)}")

            if args.show_supported and supported:
                print_package_details("📦 Still Supported Packages:", supported, is_expired=False)
            if args.show_expired and expired:
                print_package_details("☠️  Retired Packages:", expired, is_expired=True)
            print()

        conn.close()

    # --- JSON path ---
    elif source_type == "json":
        with open(source_file, "r", encoding="utf-8") as f:
            all_data = json.load(f)

        for table in TABLES:
            print(f"🔎 Table: {table}")
            table_data = all_data.get(table)
            if not table_data:
                print(f"  ⚠ No data found for '{table}' in JSON file.")
                print()
                continue

            supported, expired = query_table_json(table_data, table, ref_date)
            print(f"  ✅ Supported: {len(supported)}")
            print(f"  ❌ Expired:   {len(expired)}")

            if args.show_supported and supported:
                print_package_details("📦 Still Supported Packages:", supported, is_expired=False)
            if args.show_expired and expired:
                print_package_details("☠️  Retired Packages:", expired, is_expired=True)
            print()


if __name__ == "__main__":
    main()
