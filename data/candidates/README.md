# Directory candidates from the Civic Tech Field Guide

`civictech_guide_candidates_2026-09-26.csv` is a review file for Henry: organizations from the [Civic Tech Field Guide](https://civictech.guide) that look like they belong in the State Capacity Ecosystem directory and are not in it yet. Nothing here is live on the site. Rows go into the directory only after Henry reviews them in his sheet.

## What is in the file

223 candidates. Columns are the directory's ten, in the sheet's order, plus two review columns at the end that the sheet import can drop:

- Org Name, Description, Website: copied from the guide.
- Primary Segment, Secondary Segments: derived from the guide's organization type and categories through the crosswalk in the build script; a judgment for Henry to confirm.
- Focus: filled only when the org's own text says federal, state, or city; blank on 126 rows for Henry to set.
- Funding Model, Funding Detail: blank on every row. The guide has no funding fields.
- Problem Area, Problem Topic: derived from the categories, capped at three each.
- Source URL: the guide record. Match notes: `core` (a government-facing category) or `supporting` (a research, funder, network, fellowship or meetup category plus government language in the org's own text), the matched categories, and the guide's organization type. Core rows sort first.

## How it was built

`python3 data/candidates/build_civictech_guide_candidates.py` from the repo root. The script pages the guide's public export endpoint (`/api/v1/projects/export`, 500 records a page, until an empty page; 12,644 records on Sep 26 2026, no key needed) into a cached JSON the repo ignores, then keeps records that are active, located in the United States, typed as an organization, program, network or working group, not media or multilateral, matched by at least one crosswalk category, government-facing by category or by text, and not already in `directory.csv` by name or website domain. Exclusion counts print at the end of a run.

Guide content is CC BY 4.0. Credit "Civic Tech Field Guide" when any row goes live.
