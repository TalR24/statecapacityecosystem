"""
Build connect.json from connect_submissions.csv.

Schema (10 columns, June 2026 refresh by Henry Grunzweig):
  Name, Organization, Role, Offering, Problem Area, Problem Topic,
  Geography, Due by, Details, Contact

All multi-value fields use semicolon separators in the source CSV.
Outputs both array and first-value-string for each multi-value field so the
network page (which reads singular problem_topic / problem_area) stays compatible.
"""

import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV  = ROOT / "connect_submissions.csv"
OUT  = ROOT / "connect.json"


def norm(v):
    return (v or "").strip()


def split_semi(v):
    return [s.strip() for s in (v or "").split(";") if s.strip()]


with open(CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

people = []
for r in rows:
    name = norm(r.get("Name"))
    if not name:
        continue
    areas  = split_semi(r.get("Problem Area"))
    topics = split_semi(r.get("Problem Topic"))
    geo    = split_semi(r.get("Geography"))
    people.append({
        "id": len(people),
        "name": name,
        "organization": norm(r.get("Organization")),
        "role": norm(r.get("Role")),
        "offering": split_semi(r.get("Offering")),      # array — for connect page
        "problem_areas":  areas,                         # array — for connect page filter
        "problem_area":   areas[0]  if areas  else "",  # string — for network page compat
        "problem_topics": topics,                        # array — for connect page filter
        "problem_topic":  topics[0] if topics else "",  # string — for network page compat
        "geography": geo,                                # array — for connect page filter
        "due_by":  norm(r.get("Due by")),
        "details": norm(r.get("Details")),
        "contact": norm(r.get("Contact")),
        # The Connect page shows "Request intro" instead of a contact when this is
        # "Facilitated". An empty Contact cell means the person asked to keep
        # their details private, so introductions go through the SCE team.
        "contact_preference": "Direct" if norm(r.get("Contact")) else "Facilitated",
    })

OUT.write_text(json.dumps(people, indent=None, separators=(",", ":")))
print(f"Wrote {OUT} ({len(people)} entries)")
