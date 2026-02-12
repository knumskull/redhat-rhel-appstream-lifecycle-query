# RHEL AppStream Lifecycle Reporter

A command-line Python tool and Ansible collection to extract, query, and report the lifecycle (support/retirement) status of Red Hat Enterprise Linux (RHEL) Application Streams for RHEL 8, RHEL 9, and RHEL 10.

## Features

- Extracts lifecycle data from Red Hat's official lifecycle page.
- Stores structured data as **SQLite database**, **JSON file**, or **both**.
- JSON export enables portable, offline validation on remote RHEL systems.
- **`--check-enabled` mode** — detects locally enabled AppStream modules via `dnf` and cross-references them against lifecycle data to flag unsupported modules.
- **Ansible collection** (`rhel_appstream.lifecycle`) — a native Ansible module and role to check AppStream lifecycle status across a fleet of RHEL systems.
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

## Standalone Usage

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

### 2. Query lifecycle status (common list)

Shows the full lifecycle report for **all** AppStream modules across all tables — the reference list.

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
# Show the full lifecycle report (common list)
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

Each top-level key is a lifecycle table (`rhel8_main`, `rhel8_full`, `rhel9_rolling`, `rhel10_main`, etc.) containing its column definitions and row data as a list of dictionaries.

## Ansible Collection

The repository includes a full Ansible collection at `ansible_collections/rhel_appstream/lifecycle/` with a **custom module** and **role** for checking AppStream lifecycle status across a fleet of RHEL systems.

### Install the collection

From the repository:

```bash
cd ansible_collections/rhel_appstream/lifecycle
ansible-galaxy collection build
ansible-galaxy collection install rhel_appstream-lifecycle-1.0.0.tar.gz
```

Or install directly from the git repository:

```bash
ansible-galaxy collection install git+https://github.com/sfroemer/redhat-rhel-appstream-lifecycle-query.git#/ansible_collections/rhel_appstream/lifecycle
```

### Using the role

The role `rhel_appstream.lifecycle.check_appstream_lifecycle` handles everything: installs dependencies, distributes the JSON lifecycle data, runs the check, and reports results.

**Prerequisites:** Generate the JSON lifecycle data on your Ansible controller first:

```bash
python fetch_rhel_appstreams.py --format json
```

**Playbook example:**

```yaml
---
- name: Check RHEL AppStream lifecycle status
  hosts: rhel_servers
  become: true

  roles:
    - role: rhel_appstream.lifecycle.check_appstream_lifecycle
      vars:
        appstream_lifecycle_data_src: rhel_app_streams.json
        appstream_fail_on_expired: true
```

#### Role variables

| Variable | Default | Description |
|----------|---------|-------------|
| `appstream_check_dir` | `/opt/appstream-check` | Target directory for lifecycle data |
| `appstream_lifecycle_data_src` | `rhel_app_streams.json` | Path to JSON file on the controller |
| `appstream_fail_on_expired` | `true` | Fail the play when unsupported modules are found |
| `appstream_reference_date` | *(today)* | Reference date in `YYYY-MM-DD` format |
| `appstream_rhel_version` | *(auto-detected)* | Override RHEL major version (8, 9, or 10) |

### Using the module directly

For more control, use the `rhel_appstream.lifecycle.check_appstream_lifecycle` module in your own playbook:

```yaml
---
- name: Check AppStream lifecycle
  hosts: rhel_servers
  become: true

  tasks:
    - name: Ensure python3-dateutil is installed
      ansible.builtin.dnf:
        name: python3-dateutil
        state: present

    - name: Copy lifecycle data to target
      ansible.builtin.copy:
        src: rhel_app_streams.json
        dest: /tmp/rhel_app_streams.json

    - name: Check enabled AppStream modules
      rhel_appstream.lifecycle.check_appstream_lifecycle:
        lifecycle_data: /tmp/rhel_app_streams.json
        fail_on_expired: false
      register: result

    - name: Show summary
      ansible.builtin.debug:
        msg: "{{ result.summary }}"

    - name: List unsupported modules
      ansible.builtin.debug:
        msg: "{{ item.module }} — retired {{ item.retirement_date }} ({{ item.days_ago }} days ago)"
      loop: "{{ result.expired }}"
      loop_control:
        label: "{{ item.module }}"
      when: result.expired | length > 0
```

#### Module parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `lifecycle_data` | yes | — | Path to JSON lifecycle data on the target host |
| `reference_date` | no | *(today)* | Reference date (`YYYY-MM-DD`) |
| `fail_on_expired` | no | `true` | Fail when unsupported modules are found |
| `rhel_version` | no | *(auto)* | Override RHEL major version |

#### Module return values

| Key | Type | Description |
|-----|------|-------------|
| `enabled_modules` | list | All enabled AppStream modules found |
| `expired` | list[dict] | Modules past retirement (`module`, `retirement_date`, `days_ago`, `table`) |
| `supported` | list[dict] | Modules within lifecycle (`module`, `retirement_date`, `days_left`, `table`) |
| `unknown` | list | Enabled modules not found in lifecycle data |
| `rhel_version` | int | Detected or overridden RHEL version |
| `summary` | str | Human-readable summary |

## Output Example (standalone)

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

| Path | Description |
|------|-------------|
| `fetch_rhel_appstreams.py` | Scrapes the Red Hat lifecycle page and exports data as SQLite, JSON, or both |
| `appstream_status.py` | Queries lifecycle data, reports status, and optionally checks locally enabled modules |
| `requirements.txt` | Python dependencies |
| `ansible_collections/` | Ansible collection (`rhel_appstream.lifecycle`) |
| `ansible_collections/.../plugins/modules/check_appstream_lifecycle.py` | Custom Ansible module |
| `ansible_collections/.../roles/check_appstream_lifecycle/` | Ansible role wrapping the module |
| `LICENSE` | MIT License |

---

## License

This project is licensed under the MIT License. See `LICENSE` file for details.

## Disclaimer

This project is unofficial and not affiliated with Red Hat. It scrapes publicly available lifecycle data from Red Hat's support site. Use it at your own risk. Always verify critical lifecycle information via the official source.

## Author

This project was created with the help of AI (ChatGPT, Cursor/Claude).
Maintained by Steffen Froemer.
