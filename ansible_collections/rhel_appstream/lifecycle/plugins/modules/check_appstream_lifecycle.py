#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Steffen Froemer
# MIT License
# This code was created with the help of AI (ChatGPT, Cursor/Claude).

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
---
module: check_appstream_lifecycle
short_description: Check enabled RHEL AppStream modules against lifecycle data
version_added: "1.0.0"
description:
  - Queries locally enabled AppStream modules via C(dnf module list --enabled).
  - Cross-references each enabled module against Red Hat lifecycle data (JSON).
  - Reports which enabled modules are unsupported (past retirement date),
    supported, or unknown (not in lifecycle data).
  - Fails when unsupported modules are found (configurable via I(fail_on_expired)).
options:
  lifecycle_data:
    description:
      - Path to the JSON lifecycle data file on the target host.
      - Generate this file on a central host with
        C(python fetch_rhel_appstreams.py --format json).
    type: path
    required: true
  reference_date:
    description:
      - Reference date for the lifecycle check in C(YYYY-MM-DD) format.
      - Defaults to today if not specified.
    type: str
    required: false
  fail_on_expired:
    description:
      - Whether the module should return failure when expired modules are found.
    type: bool
    default: true
  rhel_version:
    description:
      - Override the RHEL major version (8 or 9).
      - Auto-detected from C(/etc/redhat-release) if not specified.
    type: int
    required: false
author:
  - Steffen Froemer
"""

EXAMPLES = r"""
- name: Check for unsupported AppStream modules
  rhel_appstream.lifecycle.check_appstream_lifecycle:
    lifecycle_data: /opt/appstream-check/rhel_app_streams.json
  register: lifecycle_result

- name: Show results
  ansible.builtin.debug:
    var: lifecycle_result

- name: Check without failing on expired modules
  rhel_appstream.lifecycle.check_appstream_lifecycle:
    lifecycle_data: /opt/appstream-check/rhel_app_streams.json
    fail_on_expired: false
  register: lifecycle_result

- name: Check with a specific reference date
  rhel_appstream.lifecycle.check_appstream_lifecycle:
    lifecycle_data: /opt/appstream-check/rhel_app_streams.json
    reference_date: "2025-12-31"
"""

RETURN = r"""
enabled_modules:
  description: List of all enabled AppStream modules detected on the system.
  type: list
  returned: always
  sample: ["nginx:1.22", "postgresql:15", "php:8.1"]
expired:
  description: List of enabled modules that are past their retirement date.
  type: list
  elements: dict
  returned: always
  sample:
    - module: "nginx:1.22"
      retirement_date: "November 2024"
      days_ago: 470
      table: "rhel9_main"
supported:
  description: List of enabled modules that are still within their lifecycle.
  type: list
  elements: dict
  returned: always
  sample:
    - module: "postgresql:15"
      retirement_date: "May 2027"
      days_left: 462
      table: "rhel9_full"
unknown:
  description: List of enabled modules not found in the lifecycle data.
  type: list
  returned: always
  sample: ["custom-app:1.0"]
rhel_version:
  description: Detected or overridden RHEL major version.
  type: int
  returned: always
  sample: 9
summary:
  description: Human-readable summary of the check results.
  type: str
  returned: always
"""

import json
import os
import re
import subprocess
from datetime import datetime, date

from ansible.module_utils.basic import AnsibleModule

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TABLES = [
    "rhel8_main", "rhel8_full", "rhel8_rolling", "rhel8_dependent",
    "rhel9_main", "rhel9_full", "rhel9_rolling", "rhel9_dependent",
]

RETIRE_COLS = ["Retirement Date", "End of Life", "End Date"]
NAME_COLS = ["Application Stream", "Application", "Component"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_date(date_str):
    """Parse a date string flexibly. Tries dateutil first, then common formats."""
    if not date_str or not date_str.strip():
        return None

    # Try python-dateutil first (most flexible)
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(date_str).date()
    except Exception:
        pass

    # Fallback: try common formats manually
    for fmt in ("%Y-%m-%d", "%B %Y", "%b %Y", "%m/%d/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue

    return None


def find_column(columns, candidates):
    for c in candidates:
        if c in columns:
            return c
    return None


def detect_rhel_version():
    """Detect RHEL major version from /etc/redhat-release."""
    try:
        with open("/etc/redhat-release", "r") as f:
            content = f.read()
        match = re.search(r"release\s+(\d+)", content)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def get_tables_for_version(rhel_version):
    if rhel_version:
        prefix = "rhel{0}_".format(rhel_version)
        return [t for t in TABLES if t.startswith(prefix)]
    return list(TABLES)


def get_enabled_modules(module):
    """Run 'dnf module list --enabled' and return list of name:stream pairs."""
    rc, stdout, stderr = module.run_command(
        ["dnf", "module", "list", "--enabled", "-q"],
        check_rc=False,
    )

    if rc != 0:
        lower_out = (stdout + stderr).lower()
        if "no matching" in lower_out or "no modules" in lower_out:
            return []
        module.warn("dnf returned exit code {0}: {1}".format(rc, stderr.strip()))

    modules = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Name", "Hint:", "Last metadata", "Red Hat")):
            continue

        parts = line.split()
        if len(parts) >= 2:
            name, stream = parts[0], parts[1]
            if re.match(r"^[\w][\w.\-]*$", stream):
                modules.append("{0}:{1}".format(name, stream))

    return modules


def build_lifecycle_lookup(all_data, tables, ref_date):
    """Build dict mapping lowercase app stream name to lifecycle info."""
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
            if key not in lookup or retire_date > lookup[key]["retire_date_obj"]:
                lookup[key] = {
                    "name": app_name,
                    "retire_raw": retire_raw,
                    "retire_date_obj": retire_date,
                    "days_remaining": delta_days,
                    "table": table,
                }

    return lookup


# ---------------------------------------------------------------------------
# Main module logic
# ---------------------------------------------------------------------------
def run_module():
    module_args = dict(
        lifecycle_data=dict(type="path", required=True),
        reference_date=dict(type="str", required=False, default=None),
        fail_on_expired=dict(type="bool", required=False, default=True),
        rhel_version=dict(type="int", required=False, default=None),
    )

    result = dict(
        changed=False,
        enabled_modules=[],
        expired=[],
        supported=[],
        unknown=[],
        rhel_version=None,
        summary="",
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True,
    )

    lifecycle_path = module.params["lifecycle_data"]
    ref_date_str = module.params["reference_date"]
    fail_on_expired = module.params["fail_on_expired"]
    rhel_version_override = module.params["rhel_version"]

    # --- Validate lifecycle data file ---
    if not os.path.isfile(lifecycle_path):
        module.fail_json(
            msg="Lifecycle data file not found: {0}".format(lifecycle_path),
            **result
        )

    # --- Reference date ---
    if ref_date_str:
        ref_date = parse_date(ref_date_str)
        if not ref_date:
            module.fail_json(
                msg="Invalid reference_date format: {0}. Use YYYY-MM-DD.".format(ref_date_str),
                **result
            )
    else:
        ref_date = date.today()

    # --- RHEL version ---
    rhel_version = rhel_version_override or detect_rhel_version()
    result["rhel_version"] = rhel_version

    tables = get_tables_for_version(rhel_version)

    # --- Load lifecycle data ---
    try:
        with open(lifecycle_path, "r") as f:
            all_data = json.load(f)
    except Exception as e:
        module.fail_json(
            msg="Failed to read lifecycle data: {0}".format(str(e)),
            **result
        )

    lookup = build_lifecycle_lookup(all_data, tables, ref_date)

    # --- Get enabled modules ---
    if module.check_mode:
        result["summary"] = "check_mode: would query dnf for enabled modules"
        module.exit_json(**result)

    enabled_modules = get_enabled_modules(module)
    result["enabled_modules"] = enabled_modules

    if not enabled_modules:
        result["summary"] = "No enabled AppStream modules found on this system."
        module.exit_json(**result)

    # --- Cross-reference ---
    expired = []
    supported = []
    unknown = []

    for mod in sorted(enabled_modules):
        key = mod.lower()
        info = lookup.get(key)
        if not info:
            unknown.append(mod)
        elif info["days_remaining"] < 0:
            expired.append({
                "module": mod,
                "retirement_date": info["retire_raw"],
                "days_ago": abs(info["days_remaining"]),
                "table": info["table"],
            })
        else:
            supported.append({
                "module": mod,
                "retirement_date": info["retire_raw"],
                "days_left": info["days_remaining"],
                "table": info["table"],
            })

    result["expired"] = expired
    result["supported"] = supported
    result["unknown"] = unknown

    # --- Summary ---
    parts = []
    parts.append("{0} enabled module(s) checked".format(len(enabled_modules)))
    if expired:
        parts.append("{0} UNSUPPORTED (past retirement)".format(len(expired)))
    if supported:
        parts.append("{0} supported".format(len(supported)))
    if unknown:
        parts.append("{0} unknown (not in lifecycle data)".format(len(unknown)))
    result["summary"] = "; ".join(parts)

    if expired and fail_on_expired:
        expired_names = [e["module"] for e in expired]
        module.fail_json(
            msg="Unsupported AppStream modules enabled: {0}".format(", ".join(expired_names)),
            **result
        )

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
