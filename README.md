# RHEL AppStream Lifecycle Reporter

A command-line Python tool to extract, query, and report the lifecycle (support/retirement) status of Red Hat Enterprise Linux (RHEL) Application Streams for RHEL 8 and RHEL 9.

## Features

- Extracts lifecycle data from Red Hat's official lifecycle page.
- Stores structured data in a local SQLite database.
- Queries lifecycle information with support for:
  - Custom reference date (`--date`)
  - Summary of supported/expired entries
  - Detailed listings of supported and/or expired entries
  - Days remaining until or since retirement
- Alphabetically sorted output for clarity

## Getting Started

### Prerequisites

- Python 3.8+

### Install dependencies

```bash
pip install -r requirements.txt
```

### Extract lifecycle data into SQLite

Run this to populate the database:

```bash
python fetch_rhel_appstreams.py
```

### Query lifecycle status

```bash
python appstream_status.py [options]
```

#### Options:

- `--date YYYY-MM-DD` → Set the reference date (default: today)
- `--db PATH` → Path to the SQLite database (default: `rhel_app_streams.db`)
- `--show-supported` → Show details for supported app streams
- `--show-expired` → Show details for expired/retired app streams

### Example

```bash
python appstream_status.py --show-supported --show-expired
```

## Files

- `fetch_rhel_appstreams.py` → Scrapes the Red Hat webpage and populates the SQLite database.
- `appstream_status.py` → Queries the database and prints lifecycle status.
- `requirements.txt` → Python dependencies
- `README.md` → Documentation
- `LICENSE` → MIT License

## Output Example

```
📅 Reference date: 2025-05-08

🔎 Table: rhel9_full
  ✅ Supported: 3
  ❌ Expired:   2
  📦 Still Supported Packages:
    - nginx:1.22                        → retires on 2026-06-30 (418 days left)
    - postgresql:15                     → retires on 2026-10-01 (511 days left)
```

---

## License

This project is licensed under the MIT License. See `LICENSE` file for details.

## Disclaimer

This project is unofficial and not affiliated with Red Hat. It scrapes publicly available lifecycle data from Red Hat's support site. Use it at your own risk. Always verify critical lifecycle information via the official source.

## Author

Generated with help from ChatGPT.
Maintained by Steffen Froemer.
