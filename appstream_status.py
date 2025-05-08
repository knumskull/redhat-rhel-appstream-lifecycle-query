import argparse
import sqlite3
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
    parser.add_argument(
        "--db", type=str, default="rhel_app_streams.db",
        help="Path to the SQLite database file"
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
    except:
        return None

def find_column(columns, candidates):
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None

def query_table(cursor, table, ref_date):
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

def main():
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return

    ref_date = parse_date(args.date)
    if not ref_date:
        print("❌ Invalid date format. Use YYYY-MM-DD.")
        return

    print(f"📅 Reference date: {ref_date}\n")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    for table in TABLES:
        print(f"🔎 Table: {table}")
        supported, expired = query_table(cursor, table, ref_date)
        print(f"  ✅ Supported: {len(supported)}")
        print(f"  ❌ Expired:   {len(expired)}")

        if args.show_supported and supported:
            print_package_details("📦 Still Supported Packages:", supported, is_expired=False)
        if args.show_expired and expired:
            print_package_details("☠️  Retired Packages:", expired, is_expired=True)
        print()

    conn.close()

if __name__ == "__main__":
    main()
