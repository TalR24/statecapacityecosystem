# State Capacity Ecosystem (statecapacityecosystem.com)

Last refreshed: Oct 3 2026. This file describes the site as it is now. Read it before changing anything; several collaborators edit this repo.

## What this repo is

The public site for the State Capacity Ecosystem (SCE), a network of people and organizations working on government capacity.

- **Live site:** https://statecapacityecosystem.com/ (GitHub Pages from `TalR24/statecapacityecosystem`, `main` branch, repo root; `CNAME` pins the domain).
- **Substack:** https://substack.statecapacityecosystem.com/
- **Maintainers:** Tal Roded builds the site and its visualization layer. The SCE team (Henry Grunzweig curates the organization sheet) owns the underlying database.
- **Related repos:** `TalR24/state-capacity-ecosystem` is the private work repo (CRM and archives) and never deploys. `TalR24/nycur-data-website` serves path-preserving redirect stubs at the old data.nycuriosity.com URLs, runs the monthly SCE email (`sce_monthly.yml`) and generates this site's `llms.txt`, JSON-LD and `sitemap.xml` from its `seo/` scripts.

## Site map

Every page is a hand-authored static HTML file. The shared ribbon (Home, Events, Ecosystem, Community, About, plus Search, Subscribe and Join the Slack buttons) and the footer are copy-paste identical across chrome pages, so a nav change goes into all of them.

| Section | Path | What it holds |
|---|---|---|
| Home | `/` (`index.html`) | Narrative bands: hero, problem, mission and vision, who is in the room, three-pillar loop, why it works, record stats, partners, latest, build with us |
| Events | `/events/` | Events hub; `hackathons/` (with `civic-tech-build-night/` and the rehosted `tideline/`), `sponsors-checklist/`, `demo-nights/` and `salons/` (both Coming soon, kept out of the nav until scheduled) |
| Ecosystem | `/ecosystem/` | Landing with the search entry and change feed; `search/`, `organizations/` (Organization Directory), `connect/`, `affinity-map/`, `methodology/` |
| Community | `/community/` | Landing; `slack/`, `substack/` (post hub, `mamdani-ai-priorities/` and the grocery prototype, hosted as-is), `playbooks/` (docx and pptx downloads), `proof-points/` |
| About | `/about/` | Mission, what we run, the team, interest form |
| Redirects | `databases/`, vacated paths | Meta-refresh stubs that keep query and hash; never delete one |
| Meta | `404.html`, `robots.txt`, `sitemap.xml`, `llms.txt`, `CNAME`, `.nojekyll` | Generated or fixed files (see SEO below) |

Other folders:

- `assets/`: `sce-search.js` (the one search engine), `sce_logo.png` (favicon, ribbon, hero), `proof-points/` (640x360 JPG preview per tool).
- `data/`: the pipeline, described next.
- `.github/`: workflows and the site-health docs.

## Data and build pipeline

Two source files, edited by people, never by scripts:

- `data/directory.csv`: the organization sheet (Henry's export). Ten columns read by name: Org Name, Primary Segment, Secondary Segments, Focus, Description, Funding Model, Funding Detail, Website, Problem Area, Problem Topic.
- `data/connect_submissions.csv`: the Connect directory of people and opportunities, fed by the in-page form that posts to Airtable.

Scripts (run from the repo root; `data/requirements-build.txt` lists numpy and sentence-transformers):

| Script | Reads | Writes |
|---|---|---|
| `data/build_affinity.py` | `directory.csv` | `affinity.json`, `directory.json`, `affinity_search.json` (`--require-embeddings` fails instead of falling back to TF-IDF) |
| `data/build_people.py` | `connect_submissions.csv` | `connect.json` (including `contact_preference`) |
| `data/build_changes.py` | the JSON above | `changes.json` (per-org hashes plus the last 12 refresh diffs) |
| `data/build_substack.py` | Substack archive API | `substack_posts.json` |
| `data/update_stats.py` | `affinity.json` | patches stat strings in `ecosystem/methodology/index.html` and this README |
| `data/build_static_snapshots.py` | the JSON files | pre-rendered copies of JS-built content on 7 pages (see below) |
| `data/notify_new_connect.py` | old and new `connect.json` | emails new Connect entries that carry a contact address |
| `data/site_health.py` | the whole repo | monthly drift report (see `.github/SITE_HEALTH.md`) |
| `data/candidates/build_civictech_guide_candidates.py` | Civic Tech Field Guide export | the review CSV for Henry (see `data/candidates/README.md`) |

`data/proof_points.json` is hand-maintained (11 tools). Every other `data/*.json` is generated; never hand-edit it. The builds are deterministic: the same CSV gives the same JSON.

### Affinity score

Source of truth: `data/build_affinity.py`. Text model: `sentence-transformers/all-MiniLM-L6-v2`, about 90 MB, downloaded on first run and cached.

```
score = 0.40 x P(description embedding cosine)
      + 0.30 x P(rarity-weighted topic Jaccard)
      + 0.15 x P(named-funder Jaccard)
      + 0.15 x P(segment Jaccard)
```

`P(v)` is the percentile rank among all positive values of that signal across every candidate pair (0 stays 0). Without it the tag signals decide nearly every edge, because a Jaccard over two or three tags is often 1.0.

- **Description (0.40):** embedding cosine of `name. description Topics: ...`.
- **Topics (0.30):** Jaccard over the 36 Problem Topics, each weighted `log(N / df)` so rare topics count more. Problem Areas are not a scored signal.
- **Funders (0.15):** Jaccard over funders from the `KNOWN_FUNDERS` list (with aliases) plus a regex for names ending in Foundation, Fund, Ventures, Philanthropies, Trust or Initiative. Zero when either organization has no detected funder.
- **Segments (0.15):** plain Jaccard over primary and secondary segments, no primary-segment boost.
- **Edges:** each organization keeps its K=6 strongest pairs; the edge set is the union. `mutual` marks pairs where each is in the other's top six. No score floor and no per-organization edge limit, so hubs exist. Each edge stores its shared topics, funders and terms.
- **Status:** `sunset` when the description matches the regex in `SUNSET_RE`, or the name is in `STATUS_OVERRIDES`.

Current dataset stats (refreshed by `data/update_stats.py`; do not reword these four lines, the script matches them):
- 334 orgs, 1,376 kept edges
- Funder coverage: 77/334 orgs
- Max edge: 0.97, median: 0.74 (kept edges; the map opens at the 25th percentile)

Other facts from `affinity.json`: 7 Problem Areas, 36 Problem Topics, 11 segments, 628 mutual edges, 2 sunset organizations.

### Search

`assets/sce-search.js` is the only search engine. It serves the Ecosystem landing modal, `/ecosystem/search/` and the directory search box, fetching `directory.json`, `affinity_search.json` and `connect.json` lazily. Ranking is TF-IDF cosine in the browser plus a name-substring bonus and multiplicative boosts (topic or area named in the query, place match, level match, funding intent). The default tab is a guided sentence builder (`SCESearch.mountGuide()`, goals in `SCESearch.GOALS`); the keyword tab carries `mode=search` in its URL.
For 334 orgs with rich curator-assigned tags, TF-IDF in the browser is the right split: the affinity score uses embeddings at build time, and the query has to be scored with nothing to download.
Keep the tokenizer (minimum 3 letters except `ai ml ux hr dc ev`, same stopword list) identical in `build_affinity.py`, the Affinity Map page and `sce-search.js`; `site_health.py` checks this.

### Static snapshots

Crawlers that do not run JavaScript read pre-rendered copies of JS-built blocks. `data/build_static_snapshots.py` writes them between `<!-- static:<id>:start/end -->` markers inside the element the page JS fills (the JS replaces them on load), mirroring `seo/static_snapshot.py` in the data site (this repo cannot import it). Pages: `community/index.html`, `community/proof-points/`, `ecosystem/` (change feed), `ecosystem/organizations/`, `ecosystem/connect/`, `ecosystem/methodology/`, `ecosystem/affinity-map/`. The script raises if a marker is missing, so keep the markers when editing those pages.

## Automation

| Workflow | Schedule (UTC) | What it does |
|---|---|---|
| `.github/workflows/refresh_state_capacity.yml` | daily 11:00, or manual (`force_rebuild`) | Rebuilds org JSON, stats and the change feed when `directory.csv` is newer than `affinity.json`; rebuilds `connect.json` and emails new entries when the Connect CSV changed; refreshes `substack_posts.json`; rebuilds static snapshots; commits whatever changed |
| `.github/workflows/site_health.yml` | 1st of the month 13:00, or manual | Runs `data/site_health.py` and opens or updates the `Site health: YYYY-MM` issue (label `site-health`); fails on hard failures |
| `.github/workflows/send_note.yml` | manual only | Emails a short note from the hub Gmail account |

Outside this repo:
- The "SCE site health review" Claude routine runs on the 1st at 14:05 UTC, opens at most one facts-only PR (`site-health/YYYY-MM`) and comments findings on the issue. Prompt: `.github/site_health_routine_prompt.md`.
- `sce_monthly.yml` in `nycur-data-website` (1st, 15:30 UTC) sends the single combined monthly email (site health, the review's PR and comment, Search Console data).
- Secrets, by name: `GMAIL_USER`, `GMAIL_APP_PASSWORD` (Connect notifications and `send_note.yml`). The workflows need repo Workflow permissions set to read and write.

### SEO files

`sitemap.xml` (23 URLs), `llms.txt` and the JSON-LD blocks are generated from the data site: run `python3 seo/build_sitemap.py --site sce` there after adding or renaming a page. Never hand-edit `sitemap.xml` or `llms.txt`. Every page needs the head contract (title, description, canonical, og tags); `data/site_health.py` checks it.

## Common tasks

- **Refresh organization data:** replace `data/directory.csv`, run `python3 data/build_affinity.py`, `python3 data/build_changes.py`, `python3 data/update_stats.py`, `python3 data/build_static_snapshots.py`, commit the results. The daily workflow does the same when the CSV is newer than `affinity.json`.
- **Refresh Connect data:** replace `data/connect_submissions.csv`, run `python3 data/build_people.py`.
- **Add an event:** copy `events/hackathons/civic-tech-build-night/` and follow the HTML-comment checklist at the top of the file, add a card to the events hub and the hackathons hub, regenerate the sitemap. When an event is scheduled, restore the event banner and ribbon button (the `.evt-banner` styles stay in each page head).
- **Add a Proof Points tool:** add an entry to `data/proof_points.json` with an `image` (640x360 JPG in `assets/proof-points/`), then run `build_static_snapshots.py`.
- **Add a Substack companion prototype:** host it as-is at `community/substack/<post>/` (no chrome injected), add a card to `community/substack/index.html`. Collaborator prototypes arrive through the private work repo's `substack_projects/` folder; confirm the permission line and credits first.
- **Check before pushing:** `python3 data/site_health.py`, and syntax-check inline scripts after JS edits (a `const` that shadows a parameter blanks the whole page, silently):

```bash
node -e "
const fs=require('fs');const html=fs.readFileSync('PATH/index.html','utf8');
[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(s=>s.trim()&&!s.includes('cdn.jsdelivr.net'))
.forEach((s,i)=>{try{new Function(s);console.log('script',i,'OK')}catch(e){console.log('script',i,'SYNTAX ERROR:',e.message)}});"
```

- **Push:** `git fetch && git pull` first (collaborators push through the GitHub web UI), stage explicit paths only (`git add <file>`, never `git add .` or `-A`; the folder carries `.DS_Store` and local backup files), then commit and push. Pushes authenticate with a token in the local remote; never write it down or commit it.

## Page behavior worth knowing

- **Organization Directory:** columns are Organization, Segment, Secondary Segments, Description (180 characters), Problem Area, Problem Topic; everything else is in the row detail (closest peers, Connect people, Suggest an edit, "See in network"). Filters: segment, geography, area, topic, Hide sunset organizations. URL state: `q, seg, geo, area, topic, hidesunset, page, org, add`. Suggest-an-organization posts to a Google Form.
- **Connect:** a separate dataset from the organizations. The form posts to Airtable (base `appFIPqXkeQMQ3n94`, table `tbl2ArzY6c0CdNVsh`) with a write-only token scoped to that table, in client JS on purpose. A blank Contact cell means Facilitated: the row shows a "Request intro" link (mailto plus clipboard). Contact cells must be a bare email or URL. URL state: `q, role, area, topic, offering, page, entry, add`.
- **Affinity Map:** D3 force graph. Mutual edges solid, one-way edges at 45% opacity, sunset nodes hollow. Controls: search, weight slider (default 25th percentile), segment chips, geography, area, topic, cross-segment only, hide sunset, Organizations or Funders view, path finder, neighborhood and 2-hop views. Clicking an edge explains the four component scores. URL state: `q, w, seg, geo, area, topic, cross, hidesunset, view, ego, hops, sel`.
- **Methodology:** describes only the current method. Any change to the score, weights, edge selection or map goes into this page in the same commit. `update_stats.py` patches two sentences here ("Approximately N of M organizations ..." and "N nodes and M edges, with a maximum edge score of X and a median of Y"); keep their shape. No links to Claude conversations.
- **Proof Points:** gallery from `data/proof_points.json`, filters via `?source=` and `?area=`.
- **Playbooks:** two sections, "Playbooks: run it yourself" and "Partner with us"; agency links point to `/community/playbooks/#partner`.

## Design tokens

SCE has its own brand, separate from NYCuriosity (the NYCuriosity orange breadcrumb convention does not apply here). Defined in `:root` of each chrome page: `--blue` and `--orange` both hold bronze `#8A5F1E` (the names are legacy); gold `#D4A853` for fills and the ribbon; cream body `#F4EFE4`; charcoal text `#1A1918`. Fonts are Inter and Roboto Mono.

Segment colors encode data and are not rethemed. The map lives in `SEGMENT_COLORS` in `ecosystem/affinity-map/index.html` and `ecosystem/organizations/index.html`, in `data/build_static_snapshots.py`, and as inline dots on the Methodology page; change all four together: Research `#2563eb`, Government `#0891b2`, Philanthropy `#dc2626`, Fellowships `#d97706`, Community `#7c3aed`, GovTech `#16a34a`, Advocacy `#db2777`, Digital Services & Consulting `#0d9488`, Investor `#9333ea`, Capacity Building `#ca8a04`, Ecosystems `#65a30d`.

## Rules that govern the site

1. **Copy:** no em dashes or double hyphens in prose, no "not just X, it's Y" framing, no weasel words. The owner writes new prose; automated reviews report copy problems and fix facts only (dates, counts, links).
2. **Names:** Henry Grunzweig (no "e" between z and w). The database is credited to "the SCE team", never to Henry personally. Visitors read "organizations", never "org" or "orgs"; "Org Name" stays as the sheet's column label.
3. **Weights** stay 0.40 / 0.30 / 0.15 / 0.15 with no primary-segment boost. Change them only on Tal's request, with the Methodology page updated in the same commit.
4. **No filters** for Funding Model or Named Funder on the directory (inconsistent source data, clutter). Funder text is still searchable.
5. **No links to Claude conversations** anywhere on the public site.
6. **Do not invent URLs** (Slack, Community, event pages). Use `.pending` styling for a placeholder card until the real URL exists.
7. **Rehosted projects** (TIDELINE) only with the builders' written permission, credited on the rehosted page and the event card, linked back to the source repo.
8. **No Support or Buy Me a Coffee button** in subpage headers.
9. **Substack target** is always the SCE publication, never NYCuriosity.
10. **Terminology:** the page is "Organization Directory"; the feature keeps the proper noun "Connect" ("Add Yourself to Connect"). Connect uses neutral words ("entry", "Name"), never "person" or "practitioners".
11. **Links as buttons:** standalone links use `class="sce-btn"`; a card with exactly one link becomes clickable as a whole through the `<style id="link-ux-css">` block at the end of each chrome page head (add a new card class to its `:has` rule).
12. **Hosted prototypes** (tideline, grocery, the Mamdani prototypes) are served as-is with no chrome injected.
13. **Hardcoded "300+ organizations"** copy (homepage, Ecosystem dropdown) changes only when the organization count crosses a hundred; `site_health.py` flags it.
14. **Dated backup CSVs** in `data/` are local working files; the tracked source is `directory.csv`.

## Ideas not built

- A documented-relationships layer (explicit partnerships) over the inferred affinity edges.
- A curated Funders column in Henry's sheet to replace regex extraction (77 of 334 organizations have a detected funder).
- Query-side embeddings for search (a transformers.js model of about 23 MB loaded on the first search).
- Tap-to-select with a slide-up panel for the map on phones.

## External pointers

- Source Airtable (Henry's curation): https://airtable.com/appo3EaOAi7JjI2VZ/shrAswoPpY3sbZIY7/tblcsGZwPK5O5TXjb/viwQZffbnIJ8f4zjT
- Suggest-an-organization form: https://forms.gle/GSNh2ZqUfFG4EAzF6
- Site repo: https://github.com/TalR24/statecapacityecosystem
- Monthly health process: `.github/SITE_HEALTH.md`

## Glossary

- **Affinity:** composite score 0 to 1 for how alike two organizations are. An inference from public descriptions, not a documented relationship.
- **TF-IDF:** term frequency times inverse document frequency; rare distinctive words weigh more than common ones. Used for browser search.
- **Jaccard:** intersection over union of two sets; used for topics, funders and segments.
- **Problem Area / Problem Topic:** 7 coarse buckets and 36 fine tags; Topic maps to `problem_statements` in the JSON.
- **Sunset:** an organization described as defunct or wound down; kept in the data, hollow on the map, hideable.
- **Mutual edge:** each organization is in the other's top six.
