# ---------------------------------------------------------------------------
# This code was created with the help of AI (ChatGPT, Cursor/Claude).
# Maintained by Steffen Froemer.
# ---------------------------------------------------------------------------

import argparse
import sqlite3
import json
import subprocess
import re
from datetime import datetime
from dateutil import parser as date_parser
from pathlib import Path

# Tables to check
TABLES = [
    "rhel8_main", "rhel8_full", "rhel8_rolling", "rhel8_dependent",
    "rhel9_main", "rhel9_full", "rhel9_rolling", "rhel9_dependent",
    "rhel10_main", "rhel10_full", "rhel10_rolling", "rhel10_dependent",
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
    parser.add_argument(
        "--check-enabled", action="store_true",
        help="Check locally enabled AppStream modules against lifecycle data"
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
# Detect RHEL major version
# ---------------------------------------------------------------------------
def detect_rhel_version():
    """Detect the RHEL major version from /etc/redhat-release."""
    release_file = Path("/etc/redhat-release")
    if not release_file.exists():
        return None
    try:
        content = release_file.read_text()
        match = re.search(r"release\s+(\d+)", content)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def get_tables_for_version(rhel_version):
    """Return the lifecycle tables relevant to a RHEL major version."""
    if rhel_version:
        prefix = f"rhel{rhel_version}_"
        return [t for t in TABLES if t.startswith(prefix)]
    return TABLES


# ---------------------------------------------------------------------------
# Get locally enabled AppStream modules via dnf
# ---------------------------------------------------------------------------
def get_enabled_modules():
    """Run 'dnf module list --enabled' and return a list of name:stream pairs."""
    try:
        result = subprocess.run(
            ["dnf", "module", "list", "--enabled", "-q"],
            capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        print("❌ 'dnf' command not found. --check-enabled requires a RHEL/Fedora system with dnf.")
        return None
    except subprocess.TimeoutExpired:
        print("❌ 'dnf module list --enabled' timed out.")
        return None

    if result.returncode != 0:
        # dnf returns non-zero when no modules are enabled
        if "no matching" in result.stderr.lower() or "no modules" in result.stderr.lower():
            return []
        # Also check stdout for "No matching" messages
        if "no matching" in result.stdout.lower():
            return []
        print(f"⚠ dnf returned exit code {result.returncode}")
        if result.stderr.strip():
            print(f"  stderr: {result.stderr.strip()}")

    modules = []
    # Parse the tabular output: Name  Stream  Profiles  Summary
    # Skip header lines and hint lines
    for line in result.stdout.splitlines():
        line = line.strip()
        # Skip empty lines, header separators, hints
        if not line or line.startswith("Name") or line.startswith("Hint:"):
            continue
        # Skip lines that look like section headers or metadata
        if line.startswith("Last metadata") or line.startswith("Red Hat"):
            continue

        parts = line.split()
        if len(parts) >= 2:
            name = parts[0]
            stream = parts[1]
            # Filter out non-module lines (stream should look like a version)
            # Streams are typically numeric (1.22, 8.0, 15) or short identifiers
            if re.match(r"^[\w][\w.\-]*$", stream):
                modules.append(f"{name}:{stream}")

    return modules


# ---------------------------------------------------------------------------
# Build a lifecycle lookup from all tables
# ---------------------------------------------------------------------------
def build_lifecycle_lookup_sqlite(cursor, tables, ref_date):
    """Build a dict mapping normalized app stream names to their lifecycle info."""
    lookup = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]

        retire_col = find_column(columns, RETIRE_COLS)
        name_col = find_column(columns, NAME_COLS)
        if not retire_col or not name_col:
            continue

        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        for row in rows:
            row_dict = dict(zip(col_names, row))
            app_name = row_dict.get(name_col, "").strip()
            retire_raw = row_dict.get(retire_col, "")
            retire_date = parse_date(retire_raw)
            if not app_name or not retire_date:
                continue

            delta_days = (retire_date - ref_date).days
            key = app_name.lower()
            # Keep the entry with the latest retirement date
            if key not in lookup or retire_date > lookup[key]["_retire_date"]:
                lookup[key] = {
                    "name": app_name,
                    "retire_raw": retire_raw,
                    "_retire_date": retire_date,
                    "days_remaining": delta_days,
                    "table": table,
                }

    return lookup


def build_lifecycle_lookup_json(all_data, tables, ref_date):
    """Build a dict mapping normalized app stream names to their lifecycle info."""
    lookup = {}
    for table in tables:
        table_data = all_data.get(table)
        if not table_data:
            continue

        columns = table_data.get("columns", [])
        rows = table_data.get("rows", [])

        retire_col = find_column(columns, RETIRE_COLS)
        name_col = find_column(columns, NAME_COLS)
        if not retire_col or not name_col:
            continue

        for row in rows:
            app_name = row.get(name_col, "").strip()
            retire_raw = row.get(retire_col, "")
            retire_date = parse_date(retire_raw)
            if not app_name or not retire_date:
                continue

            delta_days = (retire_date - ref_date).days
            key = app_name.lower()
            # Keep the entry with the latest retirement date
            if key not in lookup or retire_date > lookup[key]["_retire_date"]:
                lookup[key] = {
                    "name": app_name,
                    "retire_raw": retire_raw,
                    "_retire_date": retire_date,
                    "days_remaining": delta_days,
                    "table": table,
                }

    return lookup


# ---------------------------------------------------------------------------
# Check enabled modules against lifecycle data
# ---------------------------------------------------------------------------
def check_enabled_modules(lookup, enabled_modules, ref_date):
    """Cross-reference enabled modules with lifecycle data and report status."""
    supported = []
    expired = []
    unknown = []

    for module in sorted(enabled_modules):
        key = module.lower()
        info = lookup.get(key)
        if not info:
            unknown.append(module)
        elif info["days_remaining"] < 0:
            expired.append((module, info))
        else:
            supported.append((module, info))

    # --- Summary ---
    total = len(enabled_modules)
    print(f"📋 Enabled modules found: {total}\n")

    if expired:
        print(f"🚨 UNSUPPORTED — {len(expired)} enabled module(s) past retirement date:\n")
        for module, info in expired:
            days_ago = abs(info["days_remaining"])
            print(f"    ❌ {module:40} retired on {info['retire_raw']} ({days_ago} days ago)  [{info['table']}]")
        print()

    if supported:
        print(f"✅ SUPPORTED — {len(supported)} enabled module(s) still within lifecycle:\n")
        for module, info in supported:
            print(f"    ✅ {module:40} retires on {info['retire_raw']} ({info['days_remaining']} days left)  [{info['table']}]")
        print()

    if unknown:
        print(f"❓ UNKNOWN — {len(unknown)} enabled module(s) not found in lifecycle data:\n")
        for module in unknown:
            print(f"    ❓ {module}")
        print()

    # --- Exit-code-friendly summary ---
    if expired:
        print(f"⚠️  Result: {len(expired)} unsupported AppStream module(s) enabled on this system.")
    else:
        print("✅ Result: All enabled AppStream modules are within their support lifecycle.")

    return len(expired)


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

    # =======================================================================
    # --check-enabled mode: cross-reference local modules with lifecycle data
    # =======================================================================
    if args.check_enabled:
        rhel_version = detect_rhel_version()
        if rhel_version:
            print(f"🖥️  Detected RHEL {rhel_version}\n")
        else:
            print("⚠ Could not detect RHEL version — checking against all lifecycle tables.\n")

        tables = get_tables_for_version(rhel_version)

        enabled_modules = get_enabled_modules()
        if enabled_modules is None:
            return
        if not enabled_modules:
            print("ℹ️  No enabled AppStream modules found on this system.")
            return

        # Build lifecycle lookup
        if source_type == "sqlite":
            conn = sqlite3.connect(str(source_file))
            cursor = conn.cursor()
            lookup = build_lifecycle_lookup_sqlite(cursor, tables, ref_date)
            conn.close()
        else:
            with open(source_file, "r", encoding="utf-8") as f:
                all_data = json.load(f)
            lookup = build_lifecycle_lookup_json(all_data, tables, ref_date)

        expired_count = check_enabled_modules(lookup, enabled_modules, ref_date)
        raise SystemExit(1 if expired_count > 0 else 0)

    # =======================================================================
    # Default mode: report all lifecycle data
    # =======================================================================

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
