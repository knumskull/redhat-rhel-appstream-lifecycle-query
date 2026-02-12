# ---------------------------------------------------------------------------
# This code was created with the help of AI (ChatGPT, Cursor/Claude).
# Maintained by Steffen Froemer.
# ---------------------------------------------------------------------------

import argparse
import requests
from bs4 import BeautifulSoup
import sqlite3
import json
import re

# -----------------------
# Configurable variables
# -----------------------
URL = "https://access.redhat.com/support/policy/updates/rhel-app-streams-life-cycle#rhel8_full_life_application_streams"
HEADERS = {"User-Agent": "Mozilla/5.0"}

TARGET_SECTIONS = {
    "RHEL 8 Application Streams Release Life Cycle": "rhel8_main",
    "RHEL 8 Full Life Application Streams Release Life Cycle": "rhel8_full",
    "RHEL 8 Rolling Application Streams Release Life Cycle": "rhel8_rolling",
    "RHEL 8 Dependent Application Streams Release Life Cycle": "rhel8_dependent",
    "RHEL 9 Application Streams Release Life Cycle": "rhel9_main",
    "RHEL 9 Full Life Application Streams Release Life Cycle": "rhel9_full",
    "RHEL 9 Rolling Application Streams Release Life Cycle": "rhel9_rolling",
    "RHEL 9 Dependent Application Streams Release Life Cycle": "rhel9_dependent",
}

DB_NAME = "rhel_app_streams.db"
JSON_NAME = "rhel_app_streams.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fetch RHEL AppStream lifecycle data from Red Hat and store as SQLite or JSON."
    )
    parser.add_argument(
        "--format",
        choices=["sqlite", "json", "both"],
        default="sqlite",
        help="Output format: 'sqlite' (default), 'json', or 'both'",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DB_NAME,
        help=f"SQLite database filename (default: {DB_NAME})",
    )
    parser.add_argument(
        "--json-file",
        type=str,
        default=JSON_NAME,
        help=f"JSON output filename (default: {JSON_NAME})",
    )
    return parser.parse_args()


def fetch_page():
    """Download and parse the Red Hat lifecycle page."""
    response = requests.get(URL, headers=HEADERS)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_tables(soup):
    """Extract all target tables from the parsed HTML into a dict structure."""
    data = {}
    found = 0

    for header_tag in soup.find_all(["h2", "h3"]):
        title = header_tag.get_text(strip=True)
        if title not in TARGET_SECTIONS:
            continue

        table = header_tag.find_next("table")
        if not table:
            print(f"⚠ Table not found for: {title}")
            continue

        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            print(f"⚠ No headers found in table for: {title}")
            continue

        table_name = TARGET_SECTIONS[title]
        rows = []
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))

        data[table_name] = {"columns": headers, "rows": rows}
        found += 1
        print(f"✅ Extracted {len(rows)} rows for '{table_name}'")

    return data, found


def store_sqlite(data, db_path):
    """Write extracted data into a SQLite database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for table_name, table_data in data.items():
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
        headers = table_data["columns"]
        rows = table_data["rows"]

        cursor.execute(f"DROP TABLE IF EXISTS {safe_name}")
        create_cols = ", ".join([f'"{col}" TEXT' for col in headers])
        cursor.execute(f"CREATE TABLE {safe_name} ({create_cols})")

        for row in rows:
            values = [row[col] for col in headers]
            placeholders = ", ".join(["?"] * len(values))
            cursor.execute(f"INSERT INTO {safe_name} VALUES ({placeholders})", values)

        print(f"  💾 SQLite: {len(rows)} rows → '{safe_name}'")

    conn.commit()
    conn.close()
    print(f"  📁 SQLite database written to: {db_path}")


def store_json(data, json_path):
    """Write extracted data into a JSON file."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  📁 JSON file written to: {json_path}")


def main():
    args = parse_args()

    print("🌐 Fetching RHEL AppStream lifecycle data...\n")
    soup = fetch_page()
    data, found = extract_tables(soup)

    if args.format in ("sqlite", "both"):
        print(f"\n💾 Writing SQLite database...")
        store_sqlite(data, args.db)

    if args.format in ("json", "both"):
        print(f"\n📄 Writing JSON file...")
        store_json(data, args.json_file)

    print(f"\n🎉 Completed. Found and stored {found} tables out of {len(TARGET_SECTIONS)} requested.")


if __name__ == "__main__":
    main()
