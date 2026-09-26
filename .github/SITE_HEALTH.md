# Monthly site health

Two layers keep the site's copy, data and pages from drifting. Set up Sep 26 2026.

## Layer 1: the deterministic check (this repo)

`data/site_health.py`, run by `.github/workflows/site_health.yml` on the 1st of every month at 13:00 UTC (9 am New York in summer) and on demand from the Actions tab (input `external_links`, default true). It exits 1 on hard failures and writes a Markdown report that the workflow posts to a GitHub issue titled `Site health: YYYY-MM` (label `site-health`; a second run in the same month comments on the same issue) and emails to `GMAIL_USER` and statecapacityecosystem@gmail.com.

What it checks: internal links and redirect stubs; the SEO head contract and sitemap; ribbon and footer identical across chrome pages; stat strings on the Methodology page, README and homepage against `data/affinity.json`, `proof_points.json` and `substack_posts.json`; event dates still framed as upcoming after they passed, and Coming soon pages older than 120 days; Substack posts newer than the homepage Latest band; directory and Connect data contracts (taxonomy values, contacts, duplicates); tokenizer lists identical across `build_affinity.py`, the map page and `assets/sce-search.js`; copy rules (retired wording is a hard failure; em dashes, "not just" framing and placeholders are warnings); live-site status and deploy freshness; external links; the last refresh workflow run.

Run it locally from the repo root: `python3 data/site_health.py [--external]`.

## Layer 2: the judgment review (cloud routine)

A Claude Code cloud routine, "SCE site health review", runs on the 1st at 14:00 UTC (one hour after the script) on this repo with Opus 5. It reads the month's health issue, the live pages, the SCE Substack archive and the data files, and judges what the script cannot: events framed as upcoming that have passed, posts missing from Latest, Coming soon pages that overstayed, prose numbers that drifted from the data, copy that names retired features or misses shipped ones, and Methodology, README and build-script disagreements.

It may open one PR per month (branch `site-health/YYYY-MM`) containing facts only: dates, counts, links, expired event calls to action re-framed to past tense from facts already on the event page, a Latest-band card for a new post using the post's own title and subtitle verbatim, and the tools/playbooks/posts kicker. Every other change is a numbered finding on the issue (page, line, what is wrong, the fact it should reflect) for Tal to write in his own voice. The routine never edits data files or writes prose.

Manage the routine at https://claude.ai/code/routines. The prompt it runs is in `site_health_routine_prompt.md` beside this file.
