#!/usr/bin/env python3
"""
Fetch the full post archive of the SCE Substack and write data/substack_posts.json
for the Community & Platform > Substack page. Run from the repo root.

The publication lives on the custom domain substack.statecapacityecosystem.com
(since 2026-09-03; the old henrygrunzweig subdomain 404s), so the
archive API lives there. Called daily by the refresh workflow; a network
failure leaves the previous JSON in place.
"""
import json
import sys
import urllib.request
from pathlib import Path

ARCHIVE = "https://substack.statecapacityecosystem.com/api/v1/archive?sort=new&limit=50&offset={}"
OUT = Path("data/substack_posts.json")

posts, offset = [], 0
while True:
    req = urllib.request.Request(ARCHIVE.format(offset), headers={"User-Agent": "statecapacityecosystem.com build"})
    with urllib.request.urlopen(req, timeout=30) as r:
        batch = json.load(r)
    if not batch:
        break
    for p in batch:
        if p.get("audience") not in (None, "everyone"):
            continue
        posts.append({
            "title": p.get("title", "").strip(),
            "subtitle": (p.get("subtitle") or "").strip(),
            "date": (p.get("post_date") or "")[:10],
            "url": p.get("canonical_url", ""),
        })
    if len(batch) < 50:
        break
    offset += 50

if not posts:
    sys.exit("archive returned no posts; leaving existing JSON untouched")

posts.sort(key=lambda p: p["date"], reverse=True)
OUT.write_text(json.dumps(posts, indent=2, ensure_ascii=False) + "\n")
print(f"substack_posts.json: {len(posts)} posts, newest {posts[0]['date']}")
