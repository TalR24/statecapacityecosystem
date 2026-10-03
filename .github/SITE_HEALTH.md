# Monthly site health

Three parts keep the site's copy, data and pages from drifting: a deterministic script, a judgment routine and one combined email.

## 1. The deterministic check (this repo)

`data/site_health.py`, run by `.github/workflows/site_health.yml` on the 1st of every month at 13:00 UTC and on demand from the Actions tab (input `external_links`, default true). It exits 1 when there is a hard failure and writes `site_health_report.md` (an untracked artifact; delete it after a local run). The workflow posts the report to a GitHub issue titled `Site health: YYYY-MM` with label `site-health`; a second run in the same month comments on the same issue. The workflow sends no email.

What it checks:
- internal links and redirect stubs;
- the SEO head contract and the sitemap;
- ribbon and footer identical across chrome pages;
- stat strings on the Methodology page, the README and the homepage against `data/affinity.json`, `data/proof_points.json` and `data/substack_posts.json` (the README must keep the lines `- N orgs, N kept edges` and `- Funder coverage: N/N orgs`);
- event dates still framed as upcoming after they passed ("Coming soon" text is ignored), and Coming soon pages older than 120 days;
- Substack posts newer than the homepage Latest band;
- directory and Connect data contracts (taxonomy values, contacts, duplicates);
- tokenizer lists identical across `data/build_affinity.py`, the Affinity Map page and `assets/sce-search.js`;
- copy rules: retired wording is a hard failure; em dashes, "not just" framing and placeholders are warnings;
- live-site status and deploy freshness, external links, and the last run of the refresh workflow.

Run it locally from the repo root: `python3 data/site_health.py [--external]`.

## 2. The judgment review (Claude cloud routine)

The "SCE site health review" routine runs on the 1st at 14:05 UTC, after the script. It reads the month's health issue, the live pages, the SCE Substack archive and the data files, and judges what the script cannot: events framed as upcoming that have passed, posts missing from Latest, Coming soon pages that overstayed, prose numbers that disagree with the data, copy that names retired features or misses shipped ones, and disagreements between the Methodology page, the README and the build script.

It opens at most one PR per month (branch `site-health/YYYY-MM`) containing facts only: dates, counts, links, expired event calls to action re-framed to past tense from facts already on the event page, a Latest-band card for a new post using the post's own title and subtitle verbatim, and the tools, playbooks and posts kicker. Every other change is a numbered finding on the issue (page, line, what is wrong, the fact it should reflect) for the site owner to write. The routine never edits data files or writes prose.

Manage the routine at https://claude.ai/code/routines. The prompt it runs is `.github/site_health_routine_prompt.md`.

## 3. The monthly email

`sce_monthly.yml` in `TalR24/nycur-data-website` runs on the 1st at 15:30 UTC. It reruns this check, reads the issue plus the review routine's PR and comment, adds Google Search Console recommendations for the site and its Substack, and sends one HTML to-do email to Tal and statecapacityecosystem@gmail.com. Search numbers stay out of this public repo.
