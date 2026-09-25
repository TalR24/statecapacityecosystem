"""
Build affinity graph + directory data + semantic-search index for the
State Capacity Ecosystem tool.

Affinity score (composite, 0-1). Each of the four raw signals below is
converted to a percentile rank P_c over all candidate pairs before
weighting, so the composite reflects rank within this dataset rather than
raw magnitude:

  composite = 0.40 * P(description_similarity)
            + 0.30 * P(problem_topic_weighted_jaccard)
            + 0.15 * P(named_funder_jaccard)
            + 0.15 * P(segment_overlap_jaccard)

Description similarity uses sentence embeddings (sentence-transformers,
all-MiniLM-L6-v2) when available, falling back to TF-IDF cosine
otherwise. The problem-topic signal weights each topic by its rarity
(log(N/df)) so common topics contribute less than distinctive ones.
Named funders are extracted from Funding Detail text via a known-funder
list plus a capitalized-phrase pattern match. There is no funding-model
fallback: funder affinity is 0 unless both orgs have extracted funders
in common.

For each org we keep its K=6 highest-composite edges; the kept edge set
is the union across all orgs (so a node can exceed K if other nodes
independently rank it in their own top-K). There is no absolute weight
floor and no global degree cap.

The script also writes a separate affinity_search.json containing a term
vocabulary and per-org sparse TF-IDF vectors so the front-end can do
ranked semantic search at query time without an external embedding API.
"""

import argparse, csv, json, re, math, sys
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
CSV  = ROOT / "directory.csv"
OUT  = ROOT

parser = argparse.ArgumentParser()
parser.add_argument("--require-embeddings", action="store_true",
                     help="Exit non-zero instead of falling back to TF-IDF if "
                          "sentence-transformers / the model cannot load.")
args = parser.parse_args()

# Known funders likely to appear in Funding Detail. Extracted lazily and used
# for named-funder overlap. Keep names as they typically appear; matching is
# case-insensitive and tolerant of minor spelling variants.
KNOWN_FUNDERS = [
    "Families and Workers Fund",
    "Schmidt Futures", "Schmidt Sciences", "Open Philanthropy", "Omidyar Network",
    "Omidyar", "Ford Foundation", "Hewlett Foundation", "MacArthur Foundation",
    "Knight Foundation", "Bloomberg Philanthropies", "Gates Foundation",
    "Walton Family Foundation", "Walton Foundation", "Rockefeller Foundation",
    "Robert Wood Johnson Foundation", "RWJF", "Carnegie Corporation",
    "Kresge Foundation", "Surdna Foundation", "Sloan Foundation",
    "Heising-Simons Foundation", "Heising-Simons", "Patrick J. McGovern Foundation",
    "McGovern Foundation", "Doris Duke", "Arnold Ventures", "Laura and John Arnold",
    "Pew Charitable Trusts", "Pew", "Public Interest Tech Fund", "Public Interest Technology",
    "Skoll Foundation", "Skoll", "Mozilla Foundation", "Mozilla",
    "Democracy Fund", "Luminate", "Hopewell Fund", "Tides Foundation",
    "New Venture Fund", "Arabella Advisors", "Borealis Philanthropy",
    "Lever for Change", "Emerson Collective",
    "Schwartz Reisman", "Mellon Foundation", "Joyce Foundation",
    "8VC", "a16z", "Andreessen Horowitz", "Govtech Fund", "Govtech Ventures",
    "Commonweal Ventures", "Commonweal", "Kapor Capital", "Socium Ventures",
    "True Ventures", "First Round", "USDS",
    "DARPA", "NSF", "National Science Foundation",
]
# Sort by length, then alphabetically (a total order, independent of set
# iteration / hash-seed order) so we match longer names first, e.g. "Open
# Philanthropy" before "Omidyar".
KNOWN_FUNDERS = sorted(set(KNOWN_FUNDERS), key=lambda s: (-len(s), s))
KNOWN_FUNDER_RE = {
    name: re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
    for name in KNOWN_FUNDERS
}

# Funders dropped outright regardless of how they were detected.
FUNDER_BLOCKLIST = {"Web Portal Fund", "American Dynamism Fund"}
FUNDER_BLOCKLIST_LOWER = {f.lower() for f in FUNDER_BLOCKLIST}

STOPWORDS = set("""
a an the and or but if then so of in on at to for from with by about into over
through across under above between among against during before after up down out
off on as is are was were be been being have has had do does did doing this that
these those there here it its their our your his her my we they them us i you he
she who whom what which whose when where why how all any both each few more most
other some such no nor not only own same than too very can will just dont don't
also like across around within towards toward whether including include includes
focused focus orgs org organization organizations including help helps support
supports work works working primarily aimed via using used use makes make built
based across nation country wide range provide provides build building grow growing
new york nyc states programs program program's
""".split())

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]+")

# ── Status detection ─────────────────────────────────────────────────────────
SUNSET_RE = re.compile(
    r"\b(defunct|dissolved|disbanded|shut down|wound down|sunsetted|ceased operations)\b",
    re.IGNORECASE,
)
# Manual overrides for orgs whose status the description text doesn't capture.
# Henry's future Status column on the CSV will replace this dict.
STATUS_OVERRIDES = {}

# ── Geography terms ──────────────────────────────────────────────────────────
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
]
# 40 largest US cities by population (Census-ranked).
US_CITIES = [
    "New York City", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "Jacksonville",
    "Austin", "Fort Worth", "San Jose", "Charlotte", "Columbus",
    "Indianapolis", "San Francisco", "Seattle", "Denver", "Oklahoma City",
    "Nashville", "El Paso", "Washington DC", "Boston", "Las Vegas",
    "Portland", "Detroit", "Louisville", "Memphis", "Baltimore",
    "Milwaukee", "Albuquerque", "Tucson", "Fresno", "Sacramento",
    "Mesa", "Kansas City", "Atlanta", "Omaha", "Colorado Springs",
]
GEO_TERMS = sorted(
    set(US_STATES + US_CITIES + ["NYC", "New York City", "New York", "Washington DC", "D.C."]),
    key=lambda s: (-len(s), s),
)
# Leading \b (all terms start with a word char); trailing (?!\w) rather than
# \b so a term ending in punctuation (e.g. "D.C.") still matches at the end
# of a sentence, where \b would fail (no word/non-word transition between
# the term's trailing "." and a following sentence-ending ".").
GEO_TERM_RE = {g: re.compile(r"\b" + re.escape(g) + r"(?!\w)", re.IGNORECASE) for g in GEO_TERMS}


def extract_geo_terms(text: str):
    # GEO_TERMS is longest-first; once a span is claimed by a longer match
    # (e.g. "Washington DC"), a shorter overlapping match (e.g. "Washington")
    # at the same location is dropped.
    found = []
    claimed = []
    for g in GEO_TERMS:
        for m in GEO_TERM_RE[g].finditer(text):
            s, e = m.span()
            if any(s < ce and s2 < e for s2, ce in claimed):
                continue
            claimed.append((s, e))
            if g not in found:
                found.append(g)
    return found


def normalize(text: str) -> str:
    return (text or "").strip()


def tokens(text: str):
    return [t.lower() for t in WORD_RE.findall(text or "") if t.lower() not in STOPWORDS and len(t) > 2]


def parse_segments(primary: str, secondary: str):
    primary = normalize(primary)
    sec_list = [s.strip() for s in (secondary or "").split(",") if s.strip()]
    all_segs = [primary] + sec_list if primary else sec_list
    return primary, set(all_segs)


def parse_focus(focus: str):
    return [s.strip() for s in (focus or "").split(",") if s.strip()]


def parse_problem_statements(value: str):
    return [s.strip() for s in (value or "").split(",") if s.strip()]


def _canonicalize(name: str) -> str:
    canon = name
    if canon == "RWJF": canon = "Robert Wood Johnson Foundation"
    if canon == "Schmidt Sciences": canon = "Schmidt Futures"
    if canon == "Omidyar": canon = "Omidyar Network"
    if canon == "Skoll": canon = "Skoll Foundation"
    if canon == "Mozilla": canon = "Mozilla Foundation"
    if canon == "Pew": canon = "Pew Charitable Trusts"
    if canon == "Walton Foundation": canon = "Walton Family Foundation"
    if canon == "Public Interest Technology": canon = "Public Interest Tech Fund"
    if canon == "McGovern Foundation": canon = "Patrick J. McGovern Foundation"
    if canon == "Heising-Simons": canon = "Heising-Simons Foundation"
    if canon == "Laura and John Arnold": canon = "Arnold Ventures"
    if canon == "Arnold Foundation": canon = "Arnold Ventures"
    if canon == "Andreessen Horowitz": canon = "a16z"
    if canon == "Commonweal": canon = "Commonweal Ventures"
    if canon == "National Science Foundation": canon = "NSF"
    return canon


# Capitalized phrase ending in a funder-type noun, e.g. "Ford Foundation" or
# "Arnold Ventures". A lowercase connector (and, &, of, for, the) may appear
# between capitalized words so a name like "Families and Workers Fund" is
# captured whole rather than truncated to "Workers Fund". Used to catch
# funders not in KNOWN_FUNDERS.
FUNDER_PHRASE_RE = re.compile(
    # Inner words may not themselves be a funder noun, so "Ford Foundation &
    # Gates Foundation" yields two funders, not one merged phrase. "and" is
    # not a connector (it joins separate funders far more often than it sits
    # inside one name); names that need it live in KNOWN_FUNDERS.
    r"\b([A-Z][\w&.'-]+"
    r"(?: (?:(?:&|of|for|the) )?(?!(?:Foundation|Fund|Funds|Ventures|Philanthropies|Philanthropy|Trust|Initiative)\b)[A-Z][\w&.'-]+){0,4} "
    r"(?:Foundation|Fund|Funds|Ventures|Philanthropies|Philanthropy|Trust|"
    r"Charitable Trusts|Initiative))\b"
)
GENERIC_HEADS = {
    "the", "a", "our", "its", "this", "general", "private", "public",
    "federal", "state", "city", "venture", "impact",
}

WORD_ONLY_RE = re.compile(r"[a-z]+")


def extract_funders(detail: str, org_name: str = ""):
    detail = (detail or "")
    found = set()
    for name in KNOWN_FUNDERS:
        if KNOWN_FUNDER_RE[name].search(detail):
            found.add(_canonicalize(name))

    for m in FUNDER_PHRASE_RE.finditer(detail):
        phrase = m.group(1).strip()
        if len(phrase) < 8:
            continue
        head = phrase.split()[0].lower()
        if head in GENERIC_HEADS:
            continue
        found.add(_canonicalize(phrase))

    # Drop known false positives and any funder that shares 2+ words with
    # the org's own name (e.g. an org named after its own fund/foundation).
    org_words = set(WORD_ONLY_RE.findall(org_name.lower()))
    filtered = set()
    for f in found:
        if f.lower() in FUNDER_BLOCKLIST_LOWER:
            continue
        f_words = set(WORD_ONLY_RE.findall(f.lower()))
        if len(f_words & org_words) >= 2:
            continue
        filtered.add(f)
    # Drop a name contained in a longer detected name for the same org
    # ("Workers Fund" next to "Families and Workers Fund").
    return {f for f in filtered
            if not any(g != f and f.lower() in g.lower() for g in filtered)}


# ── Load ─────────────────────────────────────────────────────────────────────
with open(CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

orgs = []
for r in rows:
    name = normalize(r["Org Name"])
    if not name:
        continue
    primary_seg, all_segs = parse_segments(r["Primary Segment"], r["Secondary Segments"])
    funders = extract_funders(r["Funding Detail"], name)
    desc = normalize(r["Description"])
    sunset_match = SUNSET_RE.search(desc)
    if name in STATUS_OVERRIDES:
        status, status_note = STATUS_OVERRIDES[name]
    elif sunset_match:
        status, status_note = "sunset", sunset_match.group(0)
    else:
        status, status_note = "active", ""
    orgs.append({
        "id": len(orgs),
        "name": name,
        "status": status,
        "status_note": status_note,
        "geo_terms": extract_geo_terms(f"{name} {desc}"),
        "primary_segment": primary_seg,
        "segments": sorted(all_segs),
        "focus": parse_focus(r["Focus"]),
        "description": desc,
        "funding_model": normalize(r["Funding Model"]),
        "funding_detail": normalize(r["Funding Detail"]),
        "named_funders": sorted(funders),
        "website": normalize(r["Website"]),
        # Schema May 2026: the old "Problem Statements" column was split into
        # "Problem Area" (7 coarse buckets) and "Problem Topic" (36 fine tags).
        # We map Topic → problem_statements (same granularity as before, so the
        # existing UI + Jaccard signal carry over) and capture Area separately.
        "problem_statements": parse_problem_statements(
            r.get("Problem Topic") or r.get("Problem Statements", "")
        ),
        "problem_areas": parse_problem_statements(r.get("Problem Area", "")),
        # Token bag used for TF-IDF — folds in description, funding detail,
        # problem topics, and segments so a free-text query like "procurement"
        # can hit orgs whose description never says the word but whose tags
        # do. Problem Area names are excluded (they're coarse buckets that
        # would otherwise dominate the vocabulary).
        "_tokens": tokens(
            desc + " "
            + r.get("Funding Detail", "") + " "
            + (r.get("Problem Topic") or r.get("Problem Statements", "")).replace(",", " ") + " "
            + r.get("Primary Segment", "") + " "
            + r.get("Secondary Segments", "").replace(",", " ")
        ),
    })

n = len(orgs)
print(f"Loaded {n} orgs.")

sunset_orgs = [o for o in orgs if o["status"] == "sunset"]
print(f"Sunset orgs: {len(sunset_orgs)}")
for o in sunset_orgs:
    print(f"  sunset: {o['name']!r} — {o['status_note']!r}")

# ── TF-IDF on descriptions ───────────────────────────────────────────────────
# Kept for affinity_search.json and for shared_terms edge explanations, even
# when the description *signal* itself uses embeddings.
df = Counter()
for o in orgs:
    df.update(set(o["_tokens"]))
N = n
idf = {term: math.log((1 + N) / (1 + d)) + 1 for term, d in df.items()}

vecs = []
for o in orgs:
    tf = Counter(o["_tokens"])
    if not tf:
        vecs.append({})
        continue
    vec = {term: f * idf.get(term, 0) for term, f in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    vecs.append({k: v / norm for k, v in vec.items()})

vocab_list = sorted(idf.keys())
vocab_idx  = {t: i for i, t in enumerate(vocab_list)}

# ── Description signal: sentence embeddings, TF-IDF fallback ─────────────────
text_signal = None
desc_matrix = None
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    texts = [
        f"{o['name']}. {o['description']} Topics: {', '.join(o['problem_statements'])}."
        for o in orgs
    ]
    emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    desc_matrix = np.asarray(emb, dtype=np.float64)
    text_signal = "embeddings:all-MiniLM-L6-v2"
except Exception as exc:
    if args.require_embeddings:
        print(f"ERROR: --require-embeddings set but embeddings unavailable: {exc}", file=sys.stderr)
        sys.exit(1)
    print("WARNING: sentence-transformers unavailable, description signal = tfidf")
    text_signal = "tfidf"
    dense = np.zeros((n, len(vocab_list)), dtype=np.float64)
    for i, v in enumerate(vecs):
        for t, w in v.items():
            dense[i, vocab_idx[t]] = w
    desc_matrix = dense

print(f"Description signal: {text_signal}")

# ── Pairwise similarity (vectorized) ──────────────────────────────────────────
# np.errstate suppresses spurious divide/overflow/invalid warnings that this
# machine's Accelerate BLAS backend raises on large matmuls even though the
# results are numerically correct (verified: no NaN/Inf, matches direct dot).
np.seterr(divide="ignore", over="ignore", invalid="ignore")

desc_sim = desc_matrix @ desc_matrix.T
np.clip(desc_sim, 0.0, None, out=desc_sim)  # negative cosine has no "shared" meaning here

# Problem-topic weighted Jaccard: each topic weighted by log(N/df_t).
all_topics = sorted({t for o in orgs for t in o["problem_statements"]})
topic_idx = {t: i for i, t in enumerate(all_topics)}
topic_df = Counter()
for o in orgs:
    topic_df.update(set(o["problem_statements"]))
topic_w = np.array([math.log(n / topic_df[t]) if topic_df[t] else 0.0 for t in all_topics])

B_topic = np.zeros((n, len(all_topics)), dtype=np.float64)
for i, o in enumerate(orgs):
    for t in o["problem_statements"]:
        B_topic[i, topic_idx[t]] = 1.0
Bw_topic = B_topic * topic_w
shared_topic_w = Bw_topic @ B_topic.T
row_w_topic = Bw_topic.sum(axis=1)
union_topic_w = row_w_topic[:, None] + row_w_topic[None, :] - shared_topic_w
prob_sim = np.divide(shared_topic_w, union_topic_w,
                      out=np.zeros_like(shared_topic_w), where=union_topic_w > 0)

# Named-funder plain Jaccard (no funding-model fallback).
all_funders = sorted({f for o in orgs for f in o["named_funders"]})
funder_idx = {f: i for i, f in enumerate(all_funders)}
B_fund = np.zeros((n, len(all_funders)), dtype=np.float64)
for i, o in enumerate(orgs):
    for f in o["named_funders"]:
        B_fund[i, funder_idx[f]] = 1.0
shared_fund = B_fund @ B_fund.T
row_fund = B_fund.sum(axis=1)
union_fund = row_fund[:, None] + row_fund[None, :] - shared_fund
fund_sim = np.divide(shared_fund, union_fund,
                      out=np.zeros_like(shared_fund), where=union_fund > 0)

# Segment plain Jaccard (unchanged from before, now vectorized).
all_segments = sorted({s for o in orgs for s in o["segments"]})
segment_idx = {s: i for i, s in enumerate(all_segments)}
B_seg = np.zeros((n, len(all_segments)), dtype=np.float64)
for i, o in enumerate(orgs):
    for s in o["segments"]:
        B_seg[i, segment_idx[s]] = 1.0
shared_seg = B_seg @ B_seg.T
row_seg = B_seg.sum(axis=1)
union_seg = row_seg[:, None] + row_seg[None, :] - shared_seg
seg_sim = np.divide(shared_seg, union_seg,
                     out=np.zeros_like(shared_seg), where=union_seg > 0)

# ── Candidate pairs: all i<j ──────────────────────────────────────────────────
iu = np.triu_indices(n, k=1)
I, J = iu[0], iu[1]

desc_v = desc_sim[I, J]
prob_v = prob_sim[I, J]
fund_v = fund_sim[I, J]
seg_v  = seg_sim[I, J]


def percentile_rank(arr):
    """0 if v == 0 else (# pairs with 0 < value <= v) / (# pairs with value > 0)."""
    arr = np.asarray(arr, dtype=np.float64)
    out = np.zeros_like(arr)
    pos_mask = arr > 0
    pos_vals = arr[pos_mask]
    if pos_vals.size:
        order = np.sort(pos_vals)
        ranks = np.searchsorted(order, pos_vals, side="right")
        out[pos_mask] = ranks / pos_vals.size
    return out


n_desc = percentile_rank(desc_v)
n_prob = percentile_rank(prob_v)
n_fund = percentile_rank(fund_v)
n_seg  = percentile_rank(seg_v)

# Weights — sum to 1.0. See module docstring for rationale.
W_DESC, W_PROB, W_FUND, W_SEG = 0.40, 0.30, 0.15, 0.15
composite_v = W_DESC * n_desc + W_PROB * n_prob + W_FUND * n_fund + W_SEG * n_seg

edges_raw = []
for k in range(len(I)):
    i, j = int(I[k]), int(J[k])
    edges_raw.append({
        "source": i, "target": j,
        "weight": round(float(composite_v[k]), 4),
        "desc": round(float(desc_v[k]), 4),
        "prob": round(float(prob_v[k]), 4),
        "fund": round(float(fund_v[k]), 4),
        "seg":  round(float(seg_v[k]), 4),
        "n_desc": round(float(n_desc[k]), 4),
        "n_prob": round(float(n_prob[k]), 4),
        "n_fund": round(float(n_fund[k]), 4),
        "n_seg":  round(float(n_seg[k]), 4),
    })

print(f"Computed {len(edges_raw)} candidate pairs.")


# ── Edge selection: union of each org's top-K=6 highest-composite pairs ──────
# Ranked by the unrounded composite (composite_v), not the rounded "weight"
# field, so near-ties aren't decided by rounding.
K = 6
by_org = [[] for _ in range(n)]  # org_id -> list of (composite, pair_order, edge)
for pair_order, e in enumerate(edges_raw):
    raw = float(composite_v[pair_order])
    by_org[e["source"]].append((raw, pair_order, e))
    by_org[e["target"]].append((raw, pair_order, e))

kept_edge_ids = set()
top_k_partners = [set() for _ in range(n)]  # org_id -> set of partner org_ids in its own top-K
for org_id, candidates in enumerate(by_org):
    candidates.sort(key=lambda t: (-t[0], t[1]))
    for weight, pair_order, e in candidates[:K]:
        kept_edge_ids.add(pair_order)
        partner = e["target"] if e["source"] == org_id else e["source"]
        top_k_partners[org_id].add(partner)

edges = []
for pair_order in sorted(kept_edge_ids):
    e = dict(edges_raw[pair_order])
    i, j = e["source"], e["target"]
    e["mutual"] = j in top_k_partners[i] and i in top_k_partners[j]
    edges.append(e)

edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))

print(f"Kept {len(edges)} edges (K={K} per org, union across orgs).")


# ── Explain each edge: shared topics/funders/terms, cross-segment flag ───────
topic_sets  = [set(o["problem_statements"]) for o in orgs]
funder_sets = [set(o["named_funders"]) for o in orgs]

for e in edges:
    i, j = e["source"], e["target"]
    shared_topics = sorted(topic_sets[i] & topic_sets[j])
    shared_funders = sorted(funder_sets[i] & funder_sets[j])
    common_terms = set(vecs[i]) & set(vecs[j])
    ranked_terms = sorted(common_terms, key=lambda t: (-(vecs[i][t] * vecs[j][t]), t))[:5]
    e["shared_topics"] = shared_topics
    e["shared_funders"] = shared_funders
    e["shared_terms"] = ranked_terms
    e["cross"] = orgs[i]["primary_segment"] != orgs[j]["primary_segment"]


# ── Node degrees + peers ──────────────────────────────────────────────────────
final_deg = Counter()
neighbors = [[] for _ in range(n)]  # org_id -> list of (weight, partner_id)
for e in edges:
    i, j = e["source"], e["target"]
    final_deg[i] += 1
    final_deg[j] += 1
    neighbors[i].append((e["weight"], j))
    neighbors[j].append((e["weight"], i))

peers = []
for org_id in range(n):
    top = sorted(neighbors[org_id], key=lambda t: (-t[0], t[1]))[:3]
    peers.append([{"id": pid, "name": orgs[pid]["name"], "weight": w} for w, pid in top])


# ── Funders (top-level list, 2+ orgs) ─────────────────────────────────────────
funder_orgs = {}
for o in orgs:
    for f in o["named_funders"]:
        funder_orgs.setdefault(f, []).append(o["id"])
funders_out = sorted(
    ({"name": f, "org_ids": sorted(ids)} for f, ids in funder_orgs.items() if len(ids) >= 2),
    key=lambda d: (-len(d["org_ids"]), d["name"]),
)

# ── Emit ─────────────────────────────────────────────────────────────────────
nodes_out = [{
    "id": o["id"],
    "name": o["name"],
    "primary_segment": o["primary_segment"],
    "segments": o["segments"],
    "focus": o["focus"],
    "description": o["description"],
    "funding_model": o["funding_model"],
    "funding_detail": o["funding_detail"],
    "named_funders": o["named_funders"],
    "website": o["website"],
    "problem_statements": o["problem_statements"],
    "problem_areas": o["problem_areas"],
    "degree": final_deg.get(o["id"], 0),
    "status": o["status"],
    "status_note": o["status_note"],
    "geo_terms": o["geo_terms"],
    "peers": peers[o["id"]],
} for o in orgs]

kept_weights = sorted(e["weight"] for e in edges)


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 4)


mutual_count = sum(1 for e in edges if e["mutual"])
cross_share = round(sum(1 for e in edges if e["cross"]) / len(edges), 4) if edges else 0.0
funder_coverage = sum(1 for o in orgs if o["named_funders"])
funder_count = len({f for o in orgs for f in o["named_funders"]})

(OUT / "affinity.json").write_text(json.dumps({
    "nodes": nodes_out,
    "edges": edges,
    "funders": funders_out,
    "stats": {
        "org_count": n,
        "edge_count": len(edges),
        "max_weight": kept_weights[-1] if kept_weights else 0,
        "median_weight": pct(kept_weights, 0.5),
        "last_updated": date.today().isoformat(),
        "weights": {"desc": W_DESC, "prob": W_PROB, "fund": W_FUND, "seg": W_SEG},
        "k": K,
        "text_signal": text_signal,
        "weight_percentiles": {
            "p10": pct(kept_weights, 0.10),
            "p25": pct(kept_weights, 0.25),
            "p50": pct(kept_weights, 0.50),
            "p75": pct(kept_weights, 0.75),
            "p90": pct(kept_weights, 0.90),
        },
        "cross_share": cross_share,
        "mutual_count": mutual_count,
        "sunset_count": len(sunset_orgs),
        "funder_coverage": funder_coverage,
        "funder_count": funder_count,
    },
}, indent=None, separators=(",", ":")))

# Directory file: same node list without the graph metadata so the directory
# subpage can ship its own bundle.
(OUT / "directory.json").write_text(json.dumps(nodes_out, indent=None, separators=(",", ":")))

# ── Semantic-search index ────────────────────────────────────────────────────
# Ship a vocab + per-org sparse TF-IDF vectors so the front-end can rank orgs
# against an arbitrary natural-language query without round-tripping to an
# embedding API. Cost at query time: O(num_query_terms × num_orgs).
idf_list = [round(idf[t], 4) for t in vocab_list]

search_vectors = []
for v in vecs:
    # {term_idx: weight} — only non-zero entries
    sparse = {vocab_idx[t]: round(w, 4) for t, w in v.items() if t in vocab_idx}
    search_vectors.append(sparse)

(OUT / "affinity_search.json").write_text(json.dumps({
    "vocab": vocab_list,
    "idf":   idf_list,
    "vectors": search_vectors,
    "stats": {
        "vocab_size": len(vocab_list),
        "avg_terms_per_org": round(sum(len(v) for v in search_vectors) / max(1, n), 1),
    },
}, indent=None, separators=(",", ":")))

print(f"Wrote {OUT/'affinity.json'}")
print(f"Wrote {OUT/'directory.json'}")
print(f"Wrote {OUT/'affinity_search.json'}  (vocab={len(vocab_list)}, avg terms/org={sum(len(v) for v in search_vectors)/max(1,n):.1f})")

print()
print(f"nodes={n} edges={len(edges)} mutual={mutual_count} cross_share={cross_share}")
print(f"weight_percentiles: p10={pct(kept_weights,0.10)} p25={pct(kept_weights,0.25)} "
      f"p50={pct(kept_weights,0.50)} p75={pct(kept_weights,0.75)} p90={pct(kept_weights,0.90)}")
print(f"sunset_count={len(sunset_orgs)}: {[o['name'] for o in sunset_orgs]}")
print(f"funder_coverage={funder_coverage}/{n}  funder_count={funder_count}")
print(f"text_signal={text_signal}")
top10 = sorted(range(n), key=lambda i: -final_deg.get(i, 0))[:10]
print("Top 10 by degree:")
for i in top10:
    print(f"  {orgs[i]['name']!r}: degree={final_deg.get(i, 0)}")
