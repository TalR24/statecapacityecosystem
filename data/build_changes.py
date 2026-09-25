#!/usr/bin/env python3
"""Maintains data/changes.json: a rolling change feed of the org directory,
built from data/directory.csv. Idempotent when the directory is unchanged."""

import csv
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY_CSV = ROOT / "data" / "directory.csv"
CHANGES_JSON = ROOT / "data" / "changes.json"

MAX_ENTRIES = 12


def read_rows(text):
    reader = csv.DictReader(text.splitlines())
    rows = {}
    for row in reader:
        name = (row.get("Org Name") or "").strip()
        if name:
            rows[name] = row
    return rows


def row_hash(row):
    fields = [
        row.get("Org Name", ""), row.get("Primary Segment", ""), row.get("Secondary Segments", ""),
        row.get("Focus", ""), row.get("Description", ""), row.get("Funding Model", ""),
        row.get("Funding Detail", ""), row.get("Website", ""), row.get("Problem Area", ""),
        row.get("Problem Topic", ""),
    ]
    joined = "|".join(fields)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def previous_committed_rows():
    """Best-effort lookup of the last committed directory.csv, used only to
    identify which fields changed on an edited org (not for the hash compare,
    which uses changes.json's own state)."""
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:data/directory.csv"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return read_rows(out.stdout)
    except Exception:
        return {}


def diff_fields(old_row, new_row):
    fields = []
    for key in ["Primary Segment", "Secondary Segments", "Focus", "Description",
                "Funding Model", "Funding Detail", "Website", "Problem Area", "Problem Topic"]:
        if (old_row or {}).get(key, "") != (new_row or {}).get(key, ""):
            fields.append(key)
    return fields


def load_changes():
    if CHANGES_JSON.exists():
        return json.loads(CHANGES_JSON.read_text())
    return {"state": {}, "entries": []}


def main():
    text = DIRECTORY_CSV.read_text()
    rows = read_rows(text)
    current_hashes = {name: row_hash(row) for name, row in rows.items()}

    changes = load_changes()
    state = changes.get("state", {})
    entries = changes.get("entries", [])

    first_run = len(state) == 0

    added = sorted(n for n in current_hashes if n not in state)
    removed = sorted(n for n in state if n not in current_hashes)
    edited = sorted(n for n in current_hashes if n in state and current_hashes[n] != state[n])

    if first_run:
        changes["state"] = current_hashes
        changes["entries"] = entries
        CHANGES_JSON.write_text(json.dumps(changes, indent=2))
        print(f"build_changes: initialized state with {len(current_hashes)} organizations, no entry recorded")
        return

    if not added and not removed and not edited:
        print("build_changes: no changes detected, state unchanged")
        return

    prev_rows = previous_committed_rows()
    today = date.today().isoformat()

    edited_records = []
    for name in edited:
        fields = diff_fields(prev_rows.get(name), rows.get(name))
        # if the diff can't be determined (e.g. no committed snapshot to compare
        # against), leave fields empty; the change feed renders "updated" alone.
        edited_records.append({"name": name, "fields": fields})

    new_entry = {
        "date": today,
        "added": added,
        "removed": removed,
        "edited": edited_records,
        "counts": {"added": len(added), "removed": len(removed), "edited": len(edited_records)},
    }

    if entries and entries[0].get("date") == today:
        existing = entries[0]
        merged_added = sorted(set(existing.get("added", [])) | set(added))
        merged_removed = sorted(set(existing.get("removed", [])) | set(removed))
        merged_edited_names = {e["name"]: e["fields"] for e in existing.get("edited", [])}
        for rec in edited_records:
            merged_edited_names[rec["name"]] = sorted(set(merged_edited_names.get(rec["name"], [])) | set(rec["fields"]))
        merged_edited = [{"name": n, "fields": f} for n, f in sorted(merged_edited_names.items())]
        entries[0] = {
            "date": today,
            "added": merged_added,
            "removed": merged_removed,
            "edited": merged_edited,
            "counts": {"added": len(merged_added), "removed": len(merged_removed), "edited": len(merged_edited)},
        }
    else:
        entries.insert(0, new_entry)

    entries = entries[:MAX_ENTRIES]

    changes["entries"] = entries
    changes["state"] = current_hashes
    CHANGES_JSON.write_text(json.dumps(changes, indent=2))
    print(f"build_changes: {len(added)} added, {len(removed)} removed, {len(edited_records)} edited; entry recorded for {today}")


if __name__ == "__main__":
    main()
