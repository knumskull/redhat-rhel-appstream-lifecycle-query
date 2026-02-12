# RHEL AppStream Lifecycle Reporter

A command-line Python tool to extract, query, and report the lifecycle (support/retirement) status of Red Hat Enterprise Linux (RHEL) Application Streams for RHEL 8 and RHEL 9.

## Features

- Extracts lifecycle data from Red Hat's official lifecycle page.
- Stores structured data as **SQLite database**, **JSON file**, or **both**.
- JSON export enables portable, offline validation on remote RHEL systems (e.g. via Ansible).
- **`--check-enabled` mode** — detects locally enabled AppStream modules via `dnf` and cross-references them against lifecycle data to flag unsupported modules.
- Automatic RHEL version detection (`/etc/redhat-release`) to query only relevant lifecycle tables.
- Queries lifecycle information with support for:
  - Custom reference date (`--date`)
  - Summary of supported/expired entries
  - Detailed listings of supported and/or expired entries
  - Days remaining until or since retirement
- Auto-detects data source (JSON preferred, SQLite fallback) when no explicit source is given.
- Alphabetically sorted output for clarity.

## Getting Started

### Prerequisites

- Python 3.8+

### Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** On target RHEL systems that only consume the JSON file, only `python-dateutil` is required.
> `requests` and `beautifulsoup4` are only needed for fetching/scraping on the central host.

## Usage

### 1. Fetch lifecycle data

```bash
python fetch_rhel_appstreams.py [options]
```

#### Options

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--format` | `sqlite`, `json`, `both` | `sqlite` | Output format |
| `--db` | PATH | `rhel_app_streams.db` | SQLite database filename |
| `--json-file` | PATH | `rhel_app_streams.json` | JSON output filename |

#### Examples

```bash
# SQLite only (default, backward-compatible)
python fetch_rhel_appstreams.py

# JSON only (lightweight, portable)
python fetch_rhel_appstreams.py --format json

# Both formats at once
python fetch_rhel_appstreams.py --format both

# Custom filenames
python fetch_rhel_appstreams.py --format both --db custom.db --json-file custom.json
```

### 2. Query lifecycle status

```bash
python appstream_status.py [options]
```

#### Options

| Flag | Description |
|------|-------------|
| `--date YYYY-MM-DD` | Reference date (default: today) |
| `--db PATH` | Path to SQLite database (mutually exclusive with `--json`) |
| `--json PATH` | Path to JSON data file (mutually exclusive with `--db`) |
| `--show-supported` | Show details for supported app streams |
| `--show-expired` | Show details for expired/retired app streams |
| `--check-enabled` | Check locally enabled modules against lifecycle data |

> When neither `--db` nor `--json` is specified, auto-detection is used:
> `rhel_app_streams.json` is preferred if present, otherwise `rhel_app_streams.db`.

#### Examples

```bash
# Auto-detect data source, show all details
python appstream_status.py --show-supported --show-expired

# Explicit SQLite source
python appstream_status.py --db rhel_app_streams.db --show-expired

# Explicit JSON source
python appstream_status.py --json rhel_app_streams.json --show-supported

# Custom reference date
python appstream_status.py --json rhel_app_streams.json --date 2025-12-31 --show-expired
```

### 3. Check enabled modules on a live RHEL system

The `--check-enabled` flag queries `dnf module list --enabled` on the local system, cross-references each enabled module against the lifecycle data, and reports which ones are **unsupported** (past their retirement date).

```bash
# Check enabled modules against JSON lifecycle data
python appstream_status.py --json rhel_app_streams.json --check-enabled

# Same with SQLite
python appstream_status.py --db rhel_app_streams.db --check-enabled
```

The script will:

1. Auto-detect the RHEL major version from `/etc/redhat-release` and only check relevant lifecycle tables.
2. Run `dnf module list --enabled` to discover locally enabled AppStream modules.
3. Cross-reference each `name:stream` pair against the lifecycle data.
4. Report modules in three categories: **unsupported** (expired), **supported**, and **unknown** (not in lifecycle data).
5. Exit with code `1` if any unsupported modules are found, `0` otherwise — useful for CI/automation.

#### Example output

```
📅 Reference date: 2026-02-12
📂 Data source:    rhel_app_streams.json (json)

🖥️  Detected RHEL 9

📋 Enabled modules found: 3

🚨 UNSUPPORTED — 1 enabled module(s) past retirement date:

    ❌ nginx:1.22                            retired on November 2024 (470 days ago)  [rhel9_main]

✅ SUPPORTED — 1 enabled module(s) still within lifecycle:

    ✅ postgresql:15                          retires on May 2027 (462 days left)  [rhel9_full]

❓ UNKNOWN — 1 enabled module(s) not found in lifecycle data:

    ❓ custom-app:1.0

⚠️  Result: 1 unsupported AppStream module(s) enabled on this system.
```

## JSON Data Format

The exported JSON file follows this structure:

```json
{
  "rhel9_main": {
    "columns": ["Application Stream", "Initial Release", "Retirement Date"],
    "rows": [
      {
        "Application Stream": "nginx:1.22",
        "Initial Release": "RHEL 9.1",
        "Retirement Date": "November 2024"
      }
    ]
  }
}
```

Each top-level key is a lifecycle table (`rhel8_main`, `rhel8_full`, `rhel9_rolling`, etc.) containing its column definitions and row data as a list of dictionaries.

## Ansible Integration

The JSON export combined with `--check-enabled` makes it straightforward to validate AppStream lifecycle status across a fleet of RHEL systems — no SQLite dependency needed on the targets.

### Workflow

1. **Central host** — fetch and export the lifecycle data as JSON:

   ```bash
   python fetch_rhel_appstreams.py --format json
   ```

2. **Distribute** — copy the JSON file and query script to target hosts:

   ```yaml
   - name: Ensure target directory exists
     ansible.builtin.file:
       path: /opt/appstream-check
       state: directory
       mode: "0755"

   - name: Copy AppStream lifecycle data
     ansible.builtin.copy:
       src: rhel_app_streams.json
       dest: /opt/appstream-check/rhel_app_streams.json

   - name: Copy query script
     ansible.builtin.copy:
       src: appstream_status.py
       dest: /opt/appstream-check/appstream_status.py
       mode: "0755"
   ```

3. **Check enabled modules** — run the lifecycle check on each target:

   ```yaml
   - name: Ensure python3-dateutil is installed
     ansible.builtin.dnf:
       name: python3-dateutil
       state: present

   - name: Check for unsupported enabled AppStream modules
     ansible.builtin.command:
       cmd: >
         python3 /opt/appstream-check/appstream_status.py
         --json /opt/appstream-check/rhel_app_streams.json
         --check-enabled
     register: appstream_result
     failed_when: false
     changed_when: false

   - name: Display lifecycle check results
     ansible.builtin.debug:
       var: appstream_result.stdout_lines

   - name: Fail if unsupported modules are enabled
     ansible.builtin.fail:
       msg: "Unsupported AppStream modules detected on {{ inventory_hostname }}"
     when: appstream_result.rc != 0
   ```

> **Target host requirements:** Python 3.8+ and `python-dateutil` (`dnf install python3-dateutil`).

The `--check-enabled` flag exits with code `1` when unsupported modules are found, making it easy to use `failed_when` / `when: appstream_result.rc != 0` in Ansible to flag or fail hosts with outdated AppStreams.

## Output Example

```
📅 Reference date: 2025-05-08
📂 Data source:    rhel_app_streams.json (json)

🔎 Table: rhel9_full
  ✅ Supported: 3
  ❌ Expired:   2
  📦 Still Supported Packages:
    - nginx:1.22                        → retires on 2026-06-30 (418 days left)
    - postgresql:15                     → retires on 2026-10-01 (511 days left)
```

## Files

- `fetch_rhel_appstreams.py` — Scrapes the Red Hat lifecycle page and exports data as SQLite, JSON, or both.
- `appstream_status.py` — Queries lifecycle data from SQLite or JSON, reports status, and optionally checks locally enabled modules.
- `requirements.txt` — Python dependencies.
- `README.md` — Documentation.
- `LICENSE` — MIT License.

---

## License

This project is licensed under the MIT License. See `LICENSE` file for details.

## Disclaimer

This project is unofficial and not affiliated with Red Hat. It scrapes publicly available lifecycle data from Red Hat's support site. Use it at your own risk. Always verify critical lifecycle information via the official source.

## Author

Generated with help from ChatGPT.
Maintained by Steffen Froemer.
