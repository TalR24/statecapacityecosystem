/* SCESearch: shared ranked search over organizations (data/directory.json,
 * data/affinity_search.json) and people/opportunities (data/connect.json).
 * Used by the search modal (ecosystem/index.html, ecosystem/search/index.html)
 * and the Organization Directory search box (ecosystem/organizations/index.html).
 *
 * The tokenizer and org-ranking logic (STOPWORDS, SHORT_TERMS, GEO_FOCUS_MAP,
 * place alias groups, detectPlaceTerm, funding-intent boost) are copied
 * verbatim from ecosystem/affinity-map/index.html so all three surfaces rank
 * organizations the same way. Do not edit affinity-map's copy from here.
 */
(function (global) {
  "use strict";

  const DIR_URL    = "/data/directory.json";
  const CONNECT_URL = "/data/connect.json";
  const SEARCH_URL  = "/data/affinity_search.json";

  // ── Tokenizer (copied verbatim from ecosystem/affinity-map/index.html) ────
  const STOPWORDS = new Set("a about above across after against aimed all also among an and any are around as at based be been before being between both build building built but by can country did do does doing don't dont down during each few focus focused for from grow growing had has have he help helps her here his how i if in include includes including into is it its just like make makes more most my nation new no nor not nyc of off on only or org organization organizations orgs other our out over own primarily program program's programs provide provides range same she so some states such support supports than that the their them then there these they this those through to too toward towards under up us use used using very via was we were what when where whether which who whom whose why wide will with within work working works york you your".split(/\s+/));
  const SHORT_TERMS = new Set(["ai", "ml", "ux", "hr", "dc", "ev"]);
  function tokenize(s) {
    return (String(s || "").toLowerCase().match(/[a-z][a-z\-]+/g) || [])
      .filter(t => (t.length > 2 || SHORT_TERMS.has(t)) && !STOPWORDS.has(t));
  }
  const GEO_FOCUS_MAP = [
    { terms: ["nyc", "new york city", "new york", "city", "local", "municipal", "county"], focus: "City" },
    { terms: ["state", "albany", "statewide"], focus: "State" },
    { terms: ["federal", "national", "dc", "washington", "capitol"], focus: "Federal" },
  ];
  const FUND_INTENT_WORDS = ["fund", "funds", "funder", "funders", "funding", "foundation", "philanthropy", "investor", "invest"];
  const PLACE_ALIAS_GROUPS = [
    ["nyc", "new york city", "new york"],
    ["washington dc", "washington d.c.", "dc", "d.c."],
  ];
  const PLACE_ALIAS_MAP = (() => {
    const m = new Map();
    PLACE_ALIAS_GROUPS.forEach((group, i) => group.forEach(t => m.set(t, "group:" + i)));
    return m;
  })();
  function canonicalPlace(term) { return PLACE_ALIAS_MAP.get(term) || term; }
  function termMatches(lq, term) {
    const esc = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp("(^|[^a-z0-9])" + esc + "($|[^a-z0-9])", "i");
    return re.test(lq);
  }
  let geoTermUniverse = null;
  function buildGeoTermUniverse(orgs) {
    const terms = new Set();
    for (const o of orgs) (o.geo_terms || []).forEach(t => terms.add(String(t).toLowerCase()));
    GEO_FOCUS_MAP.forEach(g => g.terms.forEach(t => terms.add(t)));
    geoTermUniverse = [...terms].sort((a, b) => b.length - a.length);
  }
  function detectPlaceTerm(q) {
    const lq = q.toLowerCase();
    for (const t of geoTermUniverse) if (termMatches(lq, t)) return t;
    return null;
  }

  // ── Problem taxonomy (the Methodology page's areas → topics) ─────────────
  // Shared by the Problem filter menu (both search pages) and the tag boost
  // below; exposed as SCESearch.TAXONOMY so pages don't duplicate it.
  const TAXONOMY = {
    "Participatory Democracy": ["Civic Engagement", "Democracy Infrastructure", "Transparency & Accountability"],
    "Procurement & Operations": ["Operational Excellence", "Procurement Reform", "Reaction Time", "Regulatory & Administrative Burden"],
    "Service Delivery": ["Benefits Access", "Service Design"],
    "Talent & Hiring": ["Expert Contribution", "Hiring Architecture", "Hiring Process", "Talent Pipeline", "Workforce Development"],
    "Technology & Data": ["Data Integration", "Data Security", "Legacy Systems", "Shared Platforms"],
    "Test & Learn": ["Evidence Use", "Feedback Loops", "Iterative Learning", "Outcomes Measurement", "Scaling What Works"],
    "Domains": ["AI in Government", "Broadband & Internet Connectivity", "Child Welfare", "Criminal Justice", "Crisis Response", "Economic Mobility", "Education Delivery", "Healthcare Access", "Housing & Land Use", "Permitting & Licensing", "Physical Infrastructure", "Public Health", "Tax & Revenue"],
  };
  // Longest first so a query is checked against the most specific tag names first.
  const ALL_TAGS = (() => {
    const set = new Set();
    Object.keys(TAXONOMY).forEach(area => { set.add(area); TAXONOMY[area].forEach(t => set.add(t)); });
    return [...set].sort((a, b) => b.length - a.length);
  })();
  function detectTagMatches(lq) {
    return ALL_TAGS.filter(tag => lq.includes(tag.toLowerCase()));
  }

  // ── Module state ───────────────────────────────────────────────────────
  let _loaded = null;
  let _orgs = [], _people = [], _searchIdx = null;
  const _vocabIdx = new Map();
  let _orgTokenSets = [];
  let _peopleVectors = [];
  let _peopleTokenSets = [];

  function fallbackIdf() {
    const N = _orgs.length;
    return Math.log((1 + N) / 1) + 1;
  }

  function orgSearchText(o) {
    return [
      o.name, o.description, o.primary_segment,
      ...(o.segments || []), ...(o.problem_statements || []),
      ...(o.problem_areas || []), ...(o.focus || []),
    ].join(" ");
  }
  function personSearchText(p) {
    const offering = Array.isArray(p.offering) ? p.offering : [p.offering].filter(Boolean);
    return [
      p.name, p.organization, p.role, p.details,
      ...(p.problem_topics || []), ...(p.problem_areas || []),
      ...offering, ...(p.geography || []),
    ].join(" ");
  }

  function load() {
    if (_loaded) return _loaded;
    _loaded = Promise.all([
      fetch(DIR_URL).then(r => r.json()),
      fetch(CONNECT_URL).then(r => r.json()),
      fetch(SEARCH_URL).then(r => r.json()),
    ]).then(([orgs, people, idx]) => {
      _orgs = orgs; _people = people; _searchIdx = idx;
      idx.vocab.forEach((t, i) => _vocabIdx.set(t, i));
      buildGeoTermUniverse(_orgs);
      _orgTokenSets = _orgs.map(o => new Set(tokenize(orgSearchText(o))));

      _peopleTokenSets = _people.map(p => new Set(tokenize(personSearchText(p))));
      _peopleVectors = _people.map(p => {
        const toks = tokenize(personSearchText(p));
        const vec = {};
        toks.forEach(t => {
          const i = _vocabIdx.get(t);
          const key = i !== undefined ? "v" + i : "w:" + t;
          const w = i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
          vec[key] = (vec[key] || 0) + w;
        });
        let norm = 0; for (const k in vec) norm += vec[k] * vec[k];
        norm = Math.sqrt(norm) || 1;
        for (const k in vec) vec[k] /= norm;
        return vec;
      });
      return true;
    });
    return _loaded;
  }

  function queryVectorOrg(qTokens) {
    const qv = {};
    qTokens.forEach(t => {
      const i = _vocabIdx.get(t);
      if (i === undefined) return;
      qv[i] = (qv[i] || 0) + _searchIdx.idf[i];
    });
    let norm = 0; for (const k in qv) norm += qv[k] * qv[k];
    norm = Math.sqrt(norm) || 1;
    for (const k in qv) qv[k] /= norm;
    return qv;
  }
  function queryVectorPeople(qTokens) {
    const qv = {};
    qTokens.forEach(t => {
      const i = _vocabIdx.get(t);
      const key = i !== undefined ? "v" + i : "w:" + t;
      const w = i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
      qv[key] = (qv[key] || 0) + w;
    });
    let norm = 0; for (const k in qv) norm += qv[k] * qv[k];
    norm = Math.sqrt(norm) || 1;
    for (const k in qv) qv[k] /= norm;
    return qv;
  }
  function cosine(qv, ov) {
    let s = 0;
    for (const k in qv) s += qv[k] * (ov[k] || 0);
    return s;
  }
  function matchedTerms(qTokensUnique, tokenSet, limit) {
    const out = [];
    for (const t of qTokensUnique) {
      if (tokenSet.has(t)) { out.push(t); if (out.length >= limit) break; }
    }
    return out;
  }

  function problemSetsMatch(fieldA, fieldB, area, topic) {
    if (!area.size && !topic.size) return true;
    const combined = new Set([...area, ...topic]);
    return (fieldA || []).some(a => combined.has(a)) || (fieldB || []).some(t => combined.has(t));
  }

  function passesOrgFilters(o, f) {
    if (f.show === "people") return false;
    if (f.seg && f.seg.size && !f.seg.has(o.primary_segment)) return false;
    if (!problemSetsMatch(o.problem_areas, o.problem_statements, f.area || new Set(), f.topic || new Set())) return false;
    if (f.geo && f.geo.size && !(o.focus || []).some(x => f.geo.has(x))) return false;
    return true;
  }
  function passesPersonFilters(p, f) {
    if (f.show === "orgs") return false;
    if (!problemSetsMatch(p.problem_areas, p.problem_topics, f.area || new Set(), f.topic || new Set())) return false;
    if (f.geo && f.geo.size && !(p.geography || []).some(x => f.geo.has(x))) return false;
    return true;
  }

  function search(q, filters) {
    const f = Object.assign({ show: "both" }, filters || {});
    const rawQ = (q || "").trim();
    let orgsOut = [], peopleOut = [];

    if (!rawQ) {
      if (f.show !== "people") {
        _orgs.forEach(o => { if (passesOrgFilters(o, f)) orgsOut.push({ org: o, score: o.degree || 0, why: [] }); });
        orgsOut.sort((a, b) => b.score - a.score);
      }
      if (f.show !== "orgs") {
        _people.forEach(p => { if (passesPersonFilters(p, f)) peopleOut.push({ person: p, score: p.id, why: [] }); });
        peopleOut.sort((a, b) => b.score - a.score);
      }
      return { orgs: orgsOut, people: peopleOut, total: orgsOut.length + peopleOut.length };
    }

    const qTokens = tokenize(rawQ);
    const qTokensUnique = [...new Set(qTokens)];
    const lq = rawQ.toLowerCase();
    const place = detectPlaceTerm(rawQ);
    const placeCanon = place ? canonicalPlace(place) : null;
    const levelEntry = place ? GEO_FOCUS_MAP.find(g => g.terms.includes(place)) : null;
    const hasFundIntent = FUND_INTENT_WORDS.some(w => termMatches(lq, w));
    const queryTagMatches = detectTagMatches(lq);

    if (f.show !== "people") {
      const qv = queryVectorOrg(qTokens);
      _orgs.forEach((o, idx) => {
        if (!passesOrgFilters(o, f)) return;
        const ov = _searchIdx.vectors[idx];
        let s = cosine(qv, ov);
        const nameHit = o.name.toLowerCase().includes(lq);
        if (nameHit) s += 0.5;
        let geoHit = false, levelHit = false, fundHit = false;
        if (place) {
          const rawGeo = o.geo_terms || [];
          const geoCanon = rawGeo.map(x => canonicalPlace(String(x).toLowerCase()));
          if (geoCanon.includes(placeCanon)) { s *= 1.5; geoHit = true; }
          else if (rawGeo.length === 0 && levelEntry && (o.focus || []).includes(levelEntry.focus)) { s *= 1.25; levelHit = true; }
        }
        if (hasFundIntent && (o.primary_segment === "Philanthropy" || o.primary_segment === "Investor")) { s *= 1.5; fundHit = true; }
        const orgTags = queryTagMatches.filter(t => (o.problem_statements || []).includes(t) || (o.problem_areas || []).includes(t));
        if (orgTags.length) { s = (s || 0.02) * Math.pow(1.75, orgTags.length); }
        if (s <= 0.01 && !nameHit) return;
        const why = matchedTerms(qTokensUnique, _orgTokenSets[idx], 4);
        if (nameHit) why.push("name");
        if (geoHit) why.push("place: " + place);
        else if (levelHit) why.push("level: " + { City: "local", State: "state", Federal: "federal" }[levelEntry.focus]);
        if (fundHit) why.push("funding");
        orgTags.forEach(t => why.push("tag: " + t));
        orgsOut.push({ org: o, score: s, why });
      });
    }
    if (f.show !== "orgs") {
      const qv = queryVectorPeople(qTokens);
      _people.forEach((p, idx) => {
        if (!passesPersonFilters(p, f)) return;
        const pv = _peopleVectors[idx];
        let s = cosine(qv, pv);
        const nameHit = (p.name || "").toLowerCase().includes(lq);
        const orgHit = (p.organization || "").toLowerCase().includes(lq);
        if (nameHit) s += 0.5;
        if (orgHit) s += 0.25;
        const personTags = queryTagMatches.filter(t => (p.problem_topics || []).includes(t) || (p.problem_areas || []).includes(t));
        if (personTags.length) { s = (s || 0.02) * Math.pow(1.75, personTags.length); }
        if (s <= 0.01 && !nameHit && !orgHit) return;
        const why = matchedTerms(qTokensUnique, _peopleTokenSets[idx], 4);
        if (nameHit) why.push("name");
        personTags.forEach(t => why.push("tag: " + t));
        peopleOut.push({ person: p, score: s, why });
      });
    }
    orgsOut.sort((a, b) => b.score - a.score);
    peopleOut.sort((a, b) => b.score - a.score);
    return { orgs: orgsOut, people: peopleOut, total: orgsOut.length + peopleOut.length };
  }

  function nearestTopics(q, n) {
    n = n || 2;
    const qTokenSet = new Set(tokenize(q || ""));
    if (qTokenSet.size === 0) return [];
    const topics = [...new Set(_orgs.flatMap(o => o.problem_statements || []))];
    const scored = topics.map(t => {
      let s = 0;
      tokenize(t).forEach(tok => {
        if (qTokenSet.has(tok)) {
          const i = _vocabIdx.get(tok);
          s += i !== undefined ? _searchIdx.idf[i] : fallbackIdf();
        }
      });
      return { t, s };
    }).filter(x => x.s > 0);
    scored.sort((a, b) => b.s - a.s);
    return scored.slice(0, n).map(x => x.t);
  }

  // A Connect entry reads as an "Opportunity" card (vs. a "Person" card) when
  // it offers a grant/challenge or a job/fellowship AND its name looks like a
  // program name rather than a person's name (a digit, or one of these words).
  const OPPORTUNITY_NAME_WORDS = ["program", "programme", "fellowship", "fellows", "fund", "initiative", "network", "project", "lab", "center", "centre", "office", "digital", "service", "corps", "alliance", "institute", "foundation", "association", "council", "coalition", "summit", "week", "rfp", "rfei", "call", "challenge", "grant", "deployment", "partnership", "talent", "hub", "academy", "series"];
  function isOpportunity(p) {
    const offs = Array.isArray(p.offering) ? p.offering : [p.offering].filter(Boolean);
    if (!offs.includes("Grant / Challenge") && !offs.includes("Job / Fellowship")) return false;
    const name = (p.name || "").toLowerCase();
    if (/\d/.test(name)) return true;
    return OPPORTUNITY_NAME_WORDS.some(w => name.includes(w));
  }


  // ── Guided sentence builder: goal mapping and engine ─────────────────────
  // One copy of the goal mapping, read by both search pages.
  // orgs/people say which result types the goal shows; segs filters orgs by
  // primary_segment; offerings filters Connect entries (any of).
  const GOALS = {
    orgs:     { label: "organizations", orgs: true,  people: false, segs: [], offerings: [] },
    funding:  { label: "funding",                      orgs: true,  people: true,  segs: ["Philanthropy", "Investor"], offerings: ["Funding / Investment", "Grant / Challenge"] },
    jobs:     { label: "a job or fellowship",          orgs: true,  people: true,  segs: ["Fellowships"], offerings: ["Job / Fellowship"] },
    tools:    { label: "tools and vendors",            orgs: true,  people: true,  segs: ["GovTech", "Digital Services & Consulting"], offerings: ["Tool / Product"] },
    research: { label: "research and evidence",        orgs: true,  people: true,  segs: ["Research"], offerings: ["Expertise"] },
    people:   { label: "people to talk to",            orgs: false, people: true,  segs: [], offerings: ["Interesting Conversation", "Expertise", "Collaboration Opportunity"] },
    collab:   { label: "collaborators",                orgs: true,  people: true,  segs: [], offerings: ["Collaboration Opportunity"] },
    gov:      { label: "government teams",             orgs: true,  people: false, segs: ["Government"], offerings: [] },
    training: { label: "training and peer networks",   orgs: true,  people: false, segs: ["Capacity Building", "Community", "Ecosystems"], offerings: [] },
  };
  const GOAL_UNSET = { orgs: true, people: true, segs: [], offerings: [] };
  const arr = v => Array.isArray(v) ? v : (v ? [v] : []);

  // sel: {goal, areas, topics, levels} (goal is a slug; the rest are arrays or Sets).
  // Area and topic groups AND together (as on the Directory and Connect pages),
  // values within a group OR. Level filters organizations only: Connect has no
  // level filter, so its link could not carry it.
  function guided(sel) {
    sel = sel || {};
    const g = GOALS[sel.goal] || GOAL_UNSET;
    const areas = new Set(sel.areas || []), topics = new Set(sel.topics || []), levels = new Set(sel.levels || []);
    const orgs = [], people = [];
    if (g.orgs) {
      _orgs.forEach(o => {
        if (o.status === "sunset") return;
        if (g.segs.length && !g.segs.includes(o.primary_segment)) return;
        const mArea = arr(o.problem_areas).filter(a => areas.has(a));
        const mTopic = arr(o.problem_statements).filter(t => topics.has(t));
        if (areas.size && !mArea.length) return;
        if (topics.size && !mTopic.length) return;
        if (levels.size && !arr(o.focus).some(x => levels.has(x))) return;
        const why = [...mTopic, ...mArea];
        if (g.segs.length) why.push(o.primary_segment);
        orgs.push({ org: o, matched: mTopic.length + mArea.length, why });
      });
      orgs.sort((a, b) => b.matched - a.matched || (b.org.degree || 0) - (a.org.degree || 0) || a.org.name.localeCompare(b.org.name));
    }
    if (g.people) {
      _people.forEach(p => {
        const mArea = arr(p.problem_areas).filter(a => areas.has(a));
        const mTopic = arr(p.problem_topics).filter(t => topics.has(t));
        if (areas.size && !mArea.length) return;
        if (topics.size && !mTopic.length) return;
        const mOff = arr(p.offering).filter(x => g.offerings.includes(x));
        if (g.offerings.length && !mOff.length) return;
        people.push({ person: p, matched: mTopic.length + mArea.length, why: [...mTopic, ...mArea, ...mOff] });
      });
      people.sort((a, b) => b.matched - a.matched || b.person.id - a.person.id);
    }
    return { orgs, people, total: orgs.length + people.length };
  }

  global.SCESearch = { load, search, nearestTopics, TAXONOMY, isOpportunity, guided, GOALS };
})(window);

/* ── Guide me: the sentence builder UI, shared by both search surfaces ─────
 * SCESearch.mountGuide({ tabs, guide, keyword, orgCard, personCard, onChange, toKeyword })
 *   tabs / guide / keyword: element ids (tab bar, guide pane, keyword pane)
 *   orgCard / personCard: ({why, item}) => html, the pages' own card markup
 *   onChange(): called after any mode or token change (pages sync the URL)
 *   toKeyword(topic): switches the page to keyword search with the topic typed in
 * SCESearch.guideParams() returns the URLSearchParams for the current mode.
 */
(function (global) {
  "use strict";
  const S = global.SCESearch;
  const ROLES = [
    ["gov", "Government practitioner", "a "], ["tech", "Technologist", "a "], ["researcher", "Researcher", "a "],
    ["funder", "Funder", "a "], ["advocate", "Advocate", "an "], ["builder", "Capacity builder", "a "],
    ["fellowship", "Fellowship or program lead", "a "], ["journalist", "Journalist", "a "], ["newcomer", "Someone new to this", ""],
  ];
  const ROLE_DEFAULT = { funder: "orgs", tech: "gov", gov: "tools", researcher: "research", advocate: "collab", builder: "gov", fellowship: "gov", journalist: "people", newcomer: "orgs" };
  const GOAL_ORDER = ["orgs", "funding", "jobs", "tools", "research", "people", "collab", "gov", "training"];
  const LEVELS = ["Federal", "State", "City"];
  const EXAMPLES = [
    { role: "funder", goal: "orgs", topics: ["Procurement Reform"], text: "A funder looking for organizations working on Procurement Reform" },
    { role: "tech", goal: "gov", topics: ["AI in Government"], text: "A technologist looking for government teams working on AI in Government" },
    { role: "gov", goal: "tools", topics: ["Benefits Access"], text: "A government practitioner looking for tools and vendors working on Benefits Access" },
  ];
  const esc = s => (s == null ? "" : String(s)).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const roleOf = slug => ROLES.find(r => r[0] === slug);
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  const CSS = `
.sg-tabs{display:flex;gap:4px;padding:14px 32px 0;border-bottom:1px solid var(--border);}
.sg-tab{font-family:'Roboto Mono',monospace;font-size:0.8rem;font-weight:700;color:var(--text-muted);background:none;border:none;border-bottom:3px solid transparent;padding:10px 14px;cursor:pointer;min-height:40px;}
.sg-tab:hover{color:var(--text);}
.sg-tab[aria-selected="true"]{color:var(--blue);border-bottom-color:var(--blue);}
.sg-pane{padding:24px 32px 28px;}
.sg-pane[hidden],#se-kw-pane[hidden],.sg-suggest[hidden]{display:none;}
.sg-sentence{position:relative;font-size:1.2rem;line-height:2.5;color:var(--text);}
.sg-tok{font:inherit;font-weight:700;color:var(--blue);background:var(--blue-light);border:1px solid var(--blue-mid);border-radius:8px;padding:2px 10px;min-height:36px;cursor:pointer;margin:0 2px;line-height:1.4;text-align:left;}
.sg-tok:hover,.sg-tok[aria-expanded="true"]{background:var(--blue);color:#fff;}
.sg-tok.unset{font-weight:600;color:var(--text-muted);background:var(--bg);border-style:dashed;border-color:var(--border-mid);}
.sg-tok.unset:hover,.sg-tok.unset[aria-expanded="true"]{color:#fff;background:var(--blue);border-style:solid;}
.sg-hint{font-size:0.82rem;color:var(--text-muted);margin:2px 0 0;display:flex;gap:14px;flex-wrap:wrap;align-items:center;}
.sg-link{font-family:'Roboto Mono',monospace;font-size:0.75rem;font-weight:600;color:var(--blue);background:none;border:none;padding:4px 0;cursor:pointer;text-decoration:none;}
.sg-link:hover{text-decoration:underline;}
.sg-suggest{margin:12px 0 0;padding:8px 12px;background:var(--orange-light);border:1px solid #DFCEA1;border-radius:8px;font-size:0.84rem;display:flex;gap:12px;align-items:center;flex-wrap:wrap;}
.sg-suggest .sg-link{color:var(--orange);}
.sg-showing{margin:12px 0 0;display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:0.8rem;color:var(--text-muted);}
.sg-chip{font-family:'Roboto Mono',monospace;font-size:0.72rem;font-weight:600;color:var(--text-mid);background:var(--surface);border:1px solid var(--border-mid);border-radius:999px;padding:5px 11px;cursor:pointer;min-height:30px;}
.sg-chip:hover{border-color:var(--blue);color:var(--blue);}
.sg-menu{position:absolute;z-index:600;min-width:240px;max-width:min(340px,calc(100vw - 32px));max-height:320px;overflow-y:auto;background:var(--surface);border:1px solid var(--border-mid);border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,0.16);font-size:0.9rem;line-height:1.3;}
.sg-menu-filter{position:sticky;top:0;display:block;width:100%;box-sizing:border-box;border:none;border-bottom:1px solid var(--border);padding:10px 12px;font:inherit;background:var(--surface);}
.sg-opt{display:flex;align-items:center;gap:8px;width:100%;text-align:left;font:inherit;color:var(--text-mid);background:none;border:none;padding:8px 12px;min-height:36px;cursor:pointer;}
.sg-opt:hover,.sg-opt:focus{background:var(--blue-light);outline:none;}
.sg-opt[aria-selected="true"]{color:var(--blue);font-weight:700;}
.sg-opt[aria-selected="true"]::before{content:"✓";}
.sg-opt.area{font-weight:700;color:var(--text);}
.sg-opt.topic{padding-left:28px;}
.sg-menu-foot{border-top:1px solid var(--border);padding:4px 8px;position:sticky;bottom:0;background:var(--surface);}
.sg-results{margin-top:20px;border-top:1px solid var(--border);padding-top:16px;}
.sg-h{font-family:'Roboto Mono',monospace;font-size:1rem;font-weight:700;color:var(--text);margin:0 0 4px;}
.sg-count{font-size:0.86rem;color:var(--text-muted);margin:0 0 14px;}
.sg-cont{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px;}
.sg-cc{display:block;text-decoration:none;background:var(--blue-light);border:1px solid var(--blue-mid);border-radius:8px;padding:14px 16px;}
.sg-cc:hover{background:#fff;border-color:var(--blue);}
.sg-cc strong{display:block;font-family:'Roboto Mono',monospace;font-size:0.82rem;color:var(--blue);margin-bottom:4px;}
.sg-cc span{font-size:0.82rem;color:var(--text-muted);}
.sg-more{display:flex;gap:18px;flex-wrap:wrap;margin:6px 0 14px;}
.sg-next{margin-top:16px;padding-top:12px;border-top:1px solid var(--border);display:flex;gap:18px;flex-wrap:wrap;align-items:center;}
.sg-empty{text-align:center;padding:12px 8px 4px;}
.sg-empty .sg-chip{display:block;margin:8px auto;text-align:left;max-width:100%;white-space:normal;padding:8px 14px;}
@media (max-width:640px){.sg-tabs{padding:12px 16px 0;}.sg-pane{padding:18px 16px 24px;}.sg-sentence{font-size:1.05rem;}.sg-cont{grid-template-columns:1fr;}}
`;

  function mountGuide(o) {
    const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
    const tabsEl = document.getElementById(o.tabs), pane = document.getElementById(o.guide), kw = document.getElementById(o.keyword);
    const state = { mode: "guide", role: "", goal: "", areas: new Set(), topics: new Set(), levels: new Set(), dismissed: false };
    let menu = null, menuTok = null, ready = false;

    // ── URL state ──
    const prm = new URLSearchParams(location.search);
    const csv = k => (prm.get(k) || "").split(",").filter(Boolean);
    if (roleOf(prm.get("role"))) state.role = prm.get("role");
    if (S.GOALS[prm.get("goal")]) state.goal = prm.get("goal");
    csv("area").forEach(a => { if (S.TAXONOMY[a]) state.areas.add(a); });
    csv("topic").forEach(t => state.topics.add(t));
    csv("level").forEach(l => { if (LEVELS.includes(l)) state.levels.add(l); });
    const m = prm.get("mode");
    state.mode = m === "search" || m === "guide" ? m : (prm.get("q") || prm.get("seg") || prm.get("show") || prm.get("geo") ? "search" : "guide");
    // Guide params only count in guide mode; area/topic in search mode belong to the keyword filters.
    if (state.mode === "search" && m !== "guide") { state.role = ""; state.goal = ""; state.areas.clear(); state.topics.clear(); state.levels.clear(); }

    S.guideParams = function () {
      const p = new URLSearchParams();
      p.set("mode", state.mode);
      if (state.mode === "guide") {
        if (state.role) p.set("role", state.role);
        if (state.goal) p.set("goal", state.goal);
        if (state.areas.size) p.set("area", [...state.areas].join(","));
        if (state.topics.size) p.set("topic", [...state.topics].join(","));
        if (state.levels.size) p.set("level", [...state.levels].join(","));
      }
      return p;
    };
    S.guideMode = () => state.mode;
    const changed = () => { if (o.onChange) o.onChange(); };

    // ── tabs ──
    tabsEl.setAttribute("role", "tablist");
    tabsEl.className = "sg-tabs";
    tabsEl.innerHTML = `<button type="button" class="sg-tab" role="tab" id="sg-tab-guide" aria-controls="${o.guide}" data-mode="guide">Guide me</button><button type="button" class="sg-tab" role="tab" id="sg-tab-search" aria-controls="${o.keyword}" data-mode="search">Search by keyword</button>`;
    pane.setAttribute("role", "tabpanel"); pane.setAttribute("aria-labelledby", "sg-tab-guide");
    kw.setAttribute("role", "tabpanel"); kw.setAttribute("aria-labelledby", "sg-tab-search");
    function setMode(mode, silent) {
      state.mode = mode; closeMenu();
      tabsEl.querySelectorAll(".sg-tab").forEach(b => { const on = b.dataset.mode === mode; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; });
      pane.hidden = mode !== "guide"; kw.hidden = mode !== "search";
      if (!silent) changed();
    }
    tabsEl.addEventListener("click", e => { const b = e.target.closest(".sg-tab"); if (b) setMode(b.dataset.mode); });
    tabsEl.addEventListener("keydown", e => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const next = state.mode === "guide" ? "search" : "guide"; setMode(next);
      document.getElementById("sg-tab-" + next).focus();
    });

    // ── menus ──
    function closeMenu(refocus) {
      if (!menu) return;
      const tok = menuTok; menu.remove(); menu = null;
      if (tok) { tok.setAttribute("aria-expanded", "false"); if (refocus) tok.focus(); }
      menuTok = null;
    }
    function openMenu(tok, kind) {
      if (menu && menuTok === tok) { closeMenu(true); return; }
      closeMenu();
      const sent = pane.querySelector(".sg-sentence");
      menu = document.createElement("div");
      menu.className = "sg-menu"; menu.setAttribute("role", "listbox");
      if (kind === "problem" || kind === "level") menu.setAttribute("aria-multiselectable", "true");
      menu.setAttribute("aria-label", { role: "Role", goal: "Goal", problem: "Problem", level: "Level" }[kind]);
      menuTok = tok; tok.setAttribute("aria-expanded", "true");
      sent.appendChild(menu);
      const fill = () => {
        const filt = (menu.querySelector(".sg-menu-filter") || {}).value || "";
        const lf = filt.toLowerCase();
        let h = "";
        if (kind === "role") ROLES.forEach(r => h += opt("role", r[0], r[1], state.role === r[0]));
        else if (kind === "goal") GOAL_ORDER.forEach(g => h += opt("goal", g, S.GOALS[g].label, state.goal === g));
        else if (kind === "level") LEVELS.forEach(l => h += opt("level", l, l, state.levels.has(l)));
        else Object.keys(S.TAXONOMY).forEach(a => {
          const ts = S.TAXONOMY[a].filter(t => !lf || t.toLowerCase().includes(lf) || a.toLowerCase().includes(lf));
          if (!ts.length && !(a.toLowerCase().includes(lf))) return;
          h += opt("area", a, a, state.areas.has(a), "area");
          ts.forEach(t => h += opt("topic", t, t, state.topics.has(t), "topic"));
        });
        const items = menu.querySelector(".sg-menu-items"); items.innerHTML = h;
      };
      const opt = (k, v, l, sel, cls) => `<button type="button" role="option" class="sg-opt ${cls || ""}" data-k="${k}" data-v="${esc(v)}" aria-selected="${!!sel}" tabindex="-1">${esc(l)}</button>`;
      menu.innerHTML = (kind === "problem" ? `<input class="sg-menu-filter" type="text" placeholder="Filter problems" aria-label="Filter problems" autocomplete="off">` : "") +
        `<div class="sg-menu-items"></div>` + (kind !== "role" && kind !== "goal" ? `<div class="sg-menu-foot"><button type="button" class="sg-link" data-clear="1">Clear</button></div>` : "");
      fill();
      // position under the token, kept inside the sentence box
      const sr = sent.getBoundingClientRect(), tr = tok.getBoundingClientRect();
      const w = menu.offsetWidth;
      menu.style.top = (tr.bottom - sr.top + 4) + "px";
      menu.style.left = Math.max(0, Math.min(tr.left - sr.left, sr.width - w)) + "px";
      const focusables = () => [...menu.querySelectorAll("input,.sg-opt,[data-clear]")];
      const f0 = menu.querySelector(".sg-menu-filter") || menu.querySelector('.sg-opt[aria-selected="true"]') || menu.querySelector(".sg-opt");
      if (f0) f0.focus();
      menu.addEventListener("input", e => { if (e.target.classList.contains("sg-menu-filter")) fill(); });
      menu.addEventListener("click", e => {
        e.stopPropagation();
        if (e.target.closest("[data-clear]")) {
          if (kind === "problem") { state.areas.clear(); state.topics.clear(); } else state.levels.clear();
          update(); fill(); return;
        }
        const b = e.target.closest(".sg-opt"); if (!b) return;
        const v = b.dataset.v, k = b.dataset.k;
        if (k === "role") { state.role = state.role === v ? "" : v; state.dismissed = false; closeMenu(true); }
        else if (k === "goal") { state.goal = state.goal === v ? "" : v; closeMenu(true); }
        else { const set = k === "area" ? state.areas : k === "topic" ? state.topics : state.levels; set.has(v) ? set.delete(v) : set.add(v); }
        update();
        // render() rebuilds the sentence, so put focus back on the token that was just set.
        if (k === "role" || k === "goal") { const ft = pane.querySelector('.sg-tok[data-kind="' + k + '"]'); if (ft) ft.focus(); }
        if (menu) { fill(); const again = menu.querySelector(`.sg-opt[data-k="${k}"][data-v="${CSS_escape(v)}"]`); if (again) again.focus(); }
      });
      menu.addEventListener("keydown", e => {
        const f = focusables(), i = f.indexOf(document.activeElement);
        if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); closeMenu(true); }
        else if (e.key === "ArrowDown") { e.preventDefault(); f[Math.min(f.length - 1, i + 1)].focus(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); f[Math.max(0, i - 1)].focus(); }
        else if (e.key === "Tab") { e.preventDefault(); f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus(); }
      });
    }
    const CSS_escape = v => String(v).replace(/"/g, '\\"');
    document.addEventListener("click", e => { if (menu && !menu.contains(e.target) && !e.target.closest(".sg-tok")) closeMenu(); });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && menu) { e.stopImmediatePropagation(); closeMenu(true); } }, true);

    // ── sentence + results ──
    const anySet = () => state.role || state.goal || state.areas.size || state.topics.size || state.levels.size;
    const tok = (kind, text, set) => `<button type="button" class="sg-tok${set ? "" : " unset"}" data-kind="${kind}" aria-haspopup="listbox" aria-expanded="false">${set ? esc(text) : "[" + esc(text) + "]"}</button>`;
    function problemLabel() {
      const n = state.areas.size + state.topics.size;
      return n === 1 ? [...state.topics, ...state.areas][0] : n + " problems";
    }
    function linkUrl(kind, sel) {
      const g = S.GOALS[sel.goal];
      const p = [];
      const add = (k, vals, d) => { if (vals.length) p.push(k + "=" + encodeURIComponent(vals.join(d)).replace(/%7C/g, "|").replace(/%2C/g, ",")); };
      if (kind === "connect") {
        add("area", [...state.areas], "|"); add("topic", [...state.topics], "|");
        if (g) add("offering", g.offerings, "|");
        return "/ecosystem/connect/" + (p.length ? "?" + p.join("&") : "");
      }
      const d = kind === "dir" ? "|" : ",";
      if (g) add("seg", g.segs, d);
      add("geo", [...state.levels], d); add("area", [...state.areas], d); add("topic", [...state.topics], d);
      p.push("hidesunset=1");
      return (kind === "dir" ? "/ecosystem/organizations/" : "/ecosystem/affinity-map/") + "?" + p.join("&");
    }
    function showingChips() {
      const g = S.GOALS[state.goal]; if (!g) return "";
      const chips = [];
      if (!g.people) chips.push("Organizations only");
      if (!g.orgs) chips.push("People only");
      if (g.segs.length) chips.push("Segments: " + g.segs.join(", "));
      if (g.offerings.length && g.people) chips.push("Connect offering: " + g.offerings.join(", "));
      return `<div class="sg-showing"><span>Showing:</span>${chips.map(c => `<button type="button" class="sg-chip" data-rm="goal" aria-label="Remove ${esc(c)}">${esc(c)} ×</button>`).join("")}</div>`;
    }
    function render() {
      const sent = pane.querySelector(".sg-sentence");
      const r = roleOf(state.role);
      const lv = [...state.levels]; const lvl = lv.length > 1 ? lv.slice(0, -1).join(", ") + " or " + lv[lv.length - 1] : (lv[0] || "");
      sent.querySelectorAll(".sg-menu").forEach(x => { if (!menu) x.remove(); });
      const keep = menu; if (keep) keep.remove();
      sent.innerHTML = `I am ${r ? r[2] : ""}${tok("role", r ? r[1].toLowerCase() : "anyone", !!r)} looking for ${tok("goal", state.goal ? S.GOALS[state.goal].label : "anything", !!state.goal)} working on ${tok("problem", state.areas.size + state.topics.size ? problemLabel() : "any problem", !!(state.areas.size + state.topics.size))} at ${lvl ? "the " : ""}${tok("level", lvl || "any", !!lvl)} level.`;
      if (keep) { sent.appendChild(keep); const t = sent.querySelector(`.sg-tok[data-kind="${menuKind}"]`); if (t) { t.setAttribute("aria-expanded", "true"); menuTok = t; } }
      const sug = !state.goal && state.role && !state.dismissed ? ROLE_DEFAULT[state.role] : "";
      pane.querySelector(".sg-suggest").innerHTML = sug ? `<span>Suggested for ${esc(roleOf(state.role)[1])}: ${esc(S.GOALS[sug].label)}</span><button type="button" class="sg-link" data-apply="${sug}">Apply</button><button type="button" class="sg-link" data-dismiss="1" aria-label="Dismiss suggestion">Dismiss</button>` : "";
      pane.querySelector(".sg-suggest").hidden = !sug;
      pane.querySelector(".sg-showingwrap").innerHTML = showingChips();
      renderResults();
    }
    let menuKind = "";
    function renderResults() {
      const box = pane.querySelector(".sg-results");
      if (!anySet()) {
        box.innerHTML = `<div class="sg-empty"><h3 class="sg-h">Tell us who you are and what you need.</h3>${EXAMPLES.map((x, i) => `<button type="button" class="sg-chip" data-ex="${i}">${esc(x.text)}</button>`).join("")}</div>`;
        return;
      }
      if (!ready) { box.innerHTML = `<p class="sg-count">Loading…</p>`; return; }
      const sel = { goal: state.goal, areas: [...state.areas], topics: [...state.topics], levels: [...state.levels] };
      const res = S.guided(sel);
      const g = S.GOALS[state.goal];
      const showOrgs = !g || g.orgs, showPeople = !g || g.people;
      const n = res.orgs.length, mm = res.people.length;
      if (res.total === 0) {
        const rm = [];
        if (state.goal) rm.push(["goal", "Looking for: " + g.label]);
        if (state.areas.size + state.topics.size) rm.push(["problem", "Problem: " + problemLabel()]);
        if (state.levels.size) rm.push(["level", "Level: " + [...state.levels].join(", ")]);
        box.innerHTML = `<div class="sg-results-in sg-empty"><h3 class="sg-h">Nothing matches that combination yet.</h3><p class="sg-count">Try removing one:</p>${rm.map(x => `<button type="button" class="sg-chip" data-rm="${x[0]}" style="display:inline-block">${esc(x[1])} ×</button>`).join(" ")}<div class="sg-next" style="justify-content:center"><a class="sg-link" href="/ecosystem/connect/?add=1">Add yourself to Connect →</a></div></div>`;
        return;
      }
      const clauses = [];
      // A zero clause is dropped when the other side has results; "matches" only for a single clause counting one.
      if (showOrgs && (n || !mm)) clauses.push(plural(n, "organization", "organizations"));
      if (showPeople && (mm || !n)) clauses.push(plural(mm, "person or opportunity", "people or opportunities"));
      const verb = clauses.length === 1 && (n + mm) === 1 ? "matches" : "match";
      const dirU = linkUrl("dir", sel), mapU = linkUrl("map", sel), conU = linkUrl("connect", sel);
      let cards = "";
      if (showOrgs && n) cards += `<a class="sg-cc" data-card="dir" href="${esc(dirU)}"><strong>Open in the Organization Directory →</strong><span>${plural(n, "organization", "organizations")}</span></a>`;
      if (showOrgs && n) cards += `<a class="sg-cc" data-card="map" href="${esc(mapU)}"><strong>See them on the Affinity Map →</strong><span>how they connect</span></a>`;
      if (showPeople && mm) cards += `<a class="sg-cc" data-card="connect" href="${esc(conU)}"><strong>Find people on Connect →</strong><span>${plural(mm, "person or opportunity", "people or opportunities")}</span></a>`;
      const top = res.orgs.slice(0, 6).map(x => o.orgCard({ why: x.why, item: x.org })).join("") + res.people.slice(0, 4).map(x => o.personCard({ why: x.why, item: x.person })).join("");
      const more = (showOrgs && n ? `<a class="sg-link" href="${esc(dirU)}">Show all ${plural(n, "organization", "organizations")} →</a>` : "") + (showPeople && mm ? `<a class="sg-link" href="${esc(conU)}">Show all ${mm} on Connect →</a>` : "");
      box.innerHTML = `<h3 class="sg-h">Your starting point</h3><p class="sg-count">${clauses.join(" and ")} ${verb}.</p><div class="sg-cont">${cards}</div><div class="sg-top">${top}</div><div class="sg-more">${more}</div><div class="sg-next"><a class="sg-link" href="/ecosystem/connect/?add=1">Add yourself to Connect →</a><button type="button" class="sg-link" data-kw="1">Search by keyword instead →</button></div>`;
    }
    function update() { render(); changed(); }

    pane.innerHTML = `<div class="sg-sentence" aria-live="polite"></div><p class="sg-hint"><span>Pick any of the four. Results update as you go.</span><button type="button" class="sg-link" data-start="1">Start over</button><button type="button" class="sg-link" id="sg-copy">Copy link</button></p><div class="sg-suggest" hidden></div><div class="sg-showingwrap"></div><div class="sg-results"></div>`;
    pane.addEventListener("click", e => {
      const t = e.target.closest(".sg-tok");
      if (t) { menuKind = t.dataset.kind; openMenu(t, menuKind); return; }
      const rm = e.target.closest("[data-rm]");
      if (rm) { const k = rm.dataset.rm; if (k === "role") state.role = ""; if (k === "goal") state.goal = ""; if (k === "problem") { state.areas.clear(); state.topics.clear(); } if (k === "level") state.levels.clear(); update(); return; }
      if (e.target.closest("[data-start]")) { state.role = ""; state.goal = ""; state.areas.clear(); state.topics.clear(); state.levels.clear(); state.dismissed = false; update(); return; }
      const ap = e.target.closest("[data-apply]"); if (ap) { state.goal = ap.dataset.apply; update(); return; }
      if (e.target.closest("[data-dismiss]")) { state.dismissed = true; render(); return; }
      const ex = e.target.closest("[data-ex]");
      if (ex) { const x = EXAMPLES[+ex.dataset.ex]; state.role = x.role; state.goal = x.goal; state.areas.clear(); state.topics = new Set(x.topics); state.levels.clear(); update(); return; }
      if (e.target.closest("[data-kw]")) { const first = [...state.topics, ...state.areas][0] || ""; setMode("search", true); if (o.toKeyword) o.toKeyword(first); changed(); return; }
      if (e.target.closest("#sg-copy")) {
        const url = location.origin + "/ecosystem/search/?" + S.guideParams().toString();
        const b = document.getElementById("sg-copy");
        navigator.clipboard.writeText(url).then(() => { b.textContent = "Link copied"; setTimeout(() => { b.textContent = "Copy link"; }, 1500); }).catch(() => { b.textContent = url; });
      }
    });
    S.guideCopyUrl = () => location.origin + "/ecosystem/search/?" + S.guideParams().toString();
    setMode(state.mode, true);
    render();
    S.load().then(() => { ready = true; render(); });
  }
  S.mountGuide = mountGuide;
})(window);
