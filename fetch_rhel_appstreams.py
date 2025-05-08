import requests
from bs4 import BeautifulSoup
import sqlite3
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

# -----------------------
# Download page content
# -----------------------
response = requests.get(URL, headers=HEADERS)
response.raise_for_status()
html_content = response.text
soup = BeautifulSoup(html_content, "html.parser")

# -----------------------
# SQLite setup
# -----------------------
conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

# -----------------------
# Find all headers and tables
# -----------------------
found_tables = 0

for header_tag in soup.find_all(["h2", "h3"]):
    title = header_tag.get_text(strip=True)
    if title in TARGET_SECTIONS:
        table = header_tag.find_next("table")
        if not table:
            print(f"⚠ Table not found for: {title}")
            continue

        # Extract headers
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if not headers:
            print(f"⚠ No headers found in table for: {title}")
            continue

        # Prepare table name
        table_name = TARGET_SECTIONS[title]
        safe_table_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)

        # Drop and recreate table
        cursor.execute(f"DROP TABLE IF EXISTS {safe_table_name}")
        create_cols = ", ".join([f'"{col}" TEXT' for col in headers])
        cursor.execute(f"CREATE TABLE {safe_table_name} ({create_cols})")

        # Insert rows
        inserted = 0
        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) == len(headers):
                placeholders = ", ".join(["?"] * len(cells))
                cursor.execute(
                    f'INSERT INTO {safe_table_name} VALUES ({placeholders})',
                    cells
                )
                inserted += 1

        found_tables += 1
        print(f"✅ Imported {inserted} rows into table '{safe_table_name}'")

conn.commit()
conn.close()

# Summary
print(f"\n🎉 Completed. Found and stored {found_tables} tables out of {len(TARGET_SECTIONS)} requested.")

