# Design: file structure and JSON schema

Status: approved in step 2, built in step 3 (EU only). Changes since approval are listed under "Decisions".

## Decisions

- EU texts come from Cellar, France from the DILA dumps (no PISTE in v1), Spain from the BOE API.
- French dumps are filtered on `DATE_PUBLI` inside the run window.
- Nominative sections are excluded: BOE section 2, and JORF "Mesures nominatives".
- One shared HTTP client: about 1 request per second per host, a named user agent, backoff on 429 and 5xx, no retry on 403 or a WAF challenge.
- The pay-transparency example is reworded to match the Directive (see "Writing examples" below). The golden test expects the transposition deadline (Art. 34) and the Art. 5 wording "in a published job vacancy notice, prior to the job interview or otherwise".
- The France and Spain adapters flag national laws that transpose an EU directive. Art. 34(2) of Directive 2023/970 requires national measures to "contain a reference to this Directive", so the reference is a reliable signal.
- Apprentice decree golden test: €4,500 / €2,000 / €1,500 / €750, and €6,000 for apprentices with a recognised disability.
- README limitation to add: one decree can change one aid scheme while another still applies. The digest reports what the fetched text says and nothing more. Source for the example: the €5,000 "aide unique" (companies under 250 staff, up to Bac level) was set by Décret n° 2025-174 of 22 February 2025, Art. 1, which rewrote Code du travail D6243-2 II to read "Son montant est de 5 000 euros maximum" (checked in the DILA JORF dump). Décret 2025-1031 changed only the proration, and Décret 2026-168 refers to D6243-2 without amending it. service-public.fr page F23556 lists the same €5,000. The current consolidated D6243-2 (LEGI database) was not fetched, so the README cites both.
- EU pay golden test (step 3, approved): gap evidence for job ads without a salary is "unclear", not "yes", because Art. 5 also allows pay information before the interview. The job-ads recipe is marked as a weak signal with a caveat. Expected score: forcing yes (2) + findable yes (2) + early yes (2) + gap unclear (1 × 2) + crowding (0 to 2) = 8 to 10 out of 12. The rule sits in the score prompt as a general rule, not as a special case for this law.

- **No-cost plan (approved after step 3):** the weekly Action runs `--no-ai` only and saves `digests/YYYY-WW.matches.json`. The AI steps run in Claude Code through `/digest` (`.claude/skills/digest/SKILL.md`): `law-radar digest-step` writes each model request to a file, a fresh subagent answers it, and the next step reads the answer ("exchange mode" in `llm.py`). The same validator, linter, rewrite round and scoring code apply. The cap is `limits.max_documents_claude_code` (10). API mode stays as an option (`pip install -e ".[api]"` plus `ANTHROPIC_API_KEY`). No workflow sets up a key. Digests record `generated_by`: `no-ai`, `claude-code`, `api` or `replay`.
- **Golden recordings:** made with `law-radar record-fixtures` in exchange mode. Each request was answered by a fresh subagent that saw only its request file, not the tests. The recordings are stored with `"model": "claude-code"`.
- **Recipe numbers:** a list recipe may use numbers from any validated fact of the same law, the ICP or its catalogue entry. The first recording showed that limiting recipes to ICP and catalogue numbers rejected correct dates like "7 June 2027".

- **Read prompt, two general rules added during recording:** (1) for each obligation, also quote the sentence that says how or when it can be met; (2) when a text sets different amounts, thresholds or dates for different cases, give each its own fact. Neither is specific to a golden law.
- **Recording fingerprints:** every recorded answer stores a SHA-256 of its request (system prompt, user message, schema). Replay rejects a stale recording, so any prompt change forces a fresh recording. In `/digest`, a stale answer is moved aside and the request is asked again.
- **Rewrite round:** the rewriter sees every validated fact of the law and returns `fact_refs`, so it can cite the fact a number comes from instead of deleting a correct number. The same checks apply to what it returns.
- **Keywords are per language:** each language's list applies only to texts in that language. The Spanish "nómina*" matched French "nomination" before this change.
- **France (step 4):** `fr_dila.py` as described in SOURCES.md. The golden fixture is a 14-file subset of the real dump `JORF_20260307-002619.tar.gz`: the apprentice decree, a naturalisation decree (to test exclusion) and a label-rouge order (to test keyword rejection), plus the issue's table of contents.

- **Spain (step 4):** `es_boe.py` as described in SOURCES.md. Golden text: Real Decreto 126/2026 (minimum wage for 2026). The test expects €40.70 a day and €1,221 a month cited from Article 1. Rejected by keywords: BOE-A-2026-3814 (local tax reporting).
- **Writing rules added in step 4:** write numbers as digits, and never quote a passage that names a person. The second rule is also enforced in code, in the validator.
- **Validator fixes in step 4:** references to "provisions" and "disposiciones" are no longer counted as figures, and a quote under a repeated article number is checked against each article with that number separately.
- **Known gap:** the dataset catalogue has no Spanish dataset, so Spanish laws score low on "findable" and "early". Adding one needs the same verification as the French entries.

- **Publishing (step 5):** `weekly.yml` runs Monday 06:00 UTC and on demand. It runs `--no-ai`, or API mode only if an `ANTHROPIC_API_KEY` secret exists. It commits `digests/` and `state/`, opens or edits the Issue "Law radar: week NN" through `gh` (a hidden marker ties each Issue to its year and week), runs the optional channels, and builds the Pages table. `publish.yml` runs when you push a digest (after `/digest`): it edits that week's Issue and rebuilds the table. Pushes by the weekly workflow itself don't trigger it.
- **Pages on a private repo:** GitHub's free plan serves Pages only from public repositories. Both workflows always upload the table as a downloadable artifact, and deploy only when the repository variable `PAGES_ENABLED` is `true`.
- **Optional channels:** Slack (webhook), email (SMTP) and Notion (a database with the properties Name, Law ID, Market, Week, Source, Score and Next deadline, Notion API version 2022-06-28). All are off by default. A missing secret skips the channel and never fails the run. They're tested against mocked services only.

## File structure

```
law-radar/
├── README.md                  # written last, from real output
├── SOURCES.md                 # step 1
├── DESIGN.md                  # this file; folded into CONTRIBUTING.md at the end
├── CONTRIBUTING.md            # includes "Writing a source adapter"
├── LICENSE
├── pyproject.toml             # Python 3.9+ (runs on the Mac's system Python; CI also tests 3.12)
├── icp.example.yaml           # fictional Ledgerly ICP, committed
├── datasets.yaml              # catalogue of public datasets for list recipes (see below)
├── .gitignore                 # icp.yaml, .cache/, site/
│
├── law_radar/
│   ├── cli.py                 # law-radar run [--no-ai] [--since YYYY-MM-DD] [--record] [--dry-run]
│   │                          # law-radar site   (build the Pages table from digests/*.json)
│   │                          # law-radar lint "some sentence"   (handy for prompt work)
│   ├── config.py              # loads icp.yaml, or the ICP_YAML env var (from a repo secret)
│   ├── models.py              # pydantic models = the one source of the JSON schema
│   ├── http.py                # polite client (rate limit, user agent, backoff, no retry on blocks)
│   ├── state.py               # state/seen.json and state/watchlist.json
│   ├── llm.py                 # thin wrapper around the Anthropic SDK, plus replay of recorded responses
│   ├── cost.py                # token counts per model and estimated spend, printed at the end
│   │
│   ├── sources/
│   │   ├── base.py            # Source protocol: fetch_since(date) -> list[Document]
│   │   ├── eu_cellar.py
│   │   ├── fr_dila.py
│   │   └── es_boe.py
│   │
│   ├── steps/                 # one module per pipeline step, in order
│   │   ├── dedupe.py
│   │   ├── keyword_filter.py  # plain code: keywords + source classification codes
│   │   ├── model_filter.py    # Haiku: yes/no + one reason
│   │   ├── read.py            # Sonnet: structured extraction
│   │   ├── validate.py        # citation validator (drops facts, never softens)
│   │   ├── lint.py            # writing linter
│   │   ├── score.py           # Sonnet: scorecard + list recipes; totals computed in code
│   │   └── assemble.py        # builds the Digest object
│   │
│   ├── prompts/
│   │   ├── style.md           # the writing rules, banned words, before/after examples (shared)
│   │   ├── filter.md
│   │   ├── read.md
│   │   └── score.md
│   │
│   └── publish/
│       ├── markdown.py        # digests/YYYY-WW.md
│       ├── json_out.py        # digests/YYYY-WW.json
│       ├── issue.py           # "Law radar: week NN", via the gh CLI already on Actions runners
│       ├── site.py            # static HTML table, no framework
│       ├── slack.py           # optional, off by default (webhook)
│       ├── email_smtp.py      # optional, off by default (stdlib smtplib)
│       └── notion.py          # optional, off by default (Notion REST API)
│
├── schema/
│   └── digest.schema.json     # generated from models.py, checked in, tested for drift
│
├── state/
│   ├── seen.json              # IDs only, committed by the workflow
│   └── watchlist.json         # EU directives awaiting national transposition
│
├── digests/                   # YYYY-WW.md + YYYY-WW.json, committed by the workflow
│
├── tests/
│   ├── fixtures/
│   │   ├── eu/32023L0970.xhtml             # Pay Transparency Directive (real, public)
│   │   ├── eu/<fisheries CELEX>.xhtml      # irrelevant text, picked in step 3
│   │   ├── fr/JORFTEXT000053634597/        # decree 2026-168: text + article XML from DILA
│   │   ├── es/<BOE-A id>.xml               # added in step 4
│   │   └── recorded/                       # recorded model responses, keyed by step + doc id
│   ├── test_lint.py
│   ├── test_validate.py
│   ├── test_golden.py                      # the three golden documents, end to end, model mocked
│   ├── test_empty_week.py
│   ├── test_no_ai.py
│   ├── test_sources.py                     # parsers run on saved source payloads, no network
│   └── test_schema.py                      # schema file matches models.py
│
└── .github/workflows/
    ├── ci.yml                 # pytest on every push, replayed model responses, no API key needed
    └── weekly.yml             # Monday cron + workflow_dispatch: run, commit state and digests,
                               # open the Issue, deploy Pages
```

**As built in step 3:** dedupe lives in `pipeline.py`; Markdown and JSON are written by `publish/files.py`; `fixtures.py` serves the golden texts to both the tests and `law-radar record-fixtures`; the tests are `test_lint`, `test_validate`, `test_sources`, `test_filter_and_score`, `test_assemble`, `test_runs` (empty week, no-AI, state, schema) and `test_golden`.

**Pages:** `weekly.yml` builds `site/` and deploys it with the official `actions/upload-pages-artifact` and `actions/deploy-pages`. No HTML is committed.

## How a document moves through the pipeline

| Step | Input | Output | Model | Cost |
|---|---|---|---|---|
| fetch | run window | `Document[]` | none | free |
| dedupe | `Document[]`, `seen.json` | new `Document[]` | none | free |
| keyword filter | new docs, ICP keywords and codes | docs that matched, with the terms that hit | none | free |
| document cap | matched docs | at most `max_documents_per_run` | none | free |
| model filter | title + first ~2,000 characters | `FilterVerdict` (yes/no + one reason) | Haiku 4.5 | small |
| read | full text | `Extraction` (facts with citations) | Sonnet 5 | main cost |
| validate | `Extraction` + fetched text | facts that passed, and a count of dropped facts | none | free |
| lint | every generated sentence | pass, or one regeneration, or "not generated" | Sonnet 5 on retry only | small |
| score | validated facts + `datasets.yaml` | `Scorecard` + up to 3 `ListRecipe`s | Sonnet 5 | small |
| publish | `Digest` | md, json, Issue, Pages | none | free |

`--no-ai` stops after the cap. Every matched document is published as a `NoAiEntry` (title, date, link, matched terms).

The cap is applied before any model call, so it bounds spend. Documents over the cap are **not** marked seen. They wait for the next run, and the digest says how many were deferred.

A document on `watchlist.json` (a national text that references a watched directive) skips the keyword filter. Transpositions can have dull titles.

## Citation validator (the rules)

A fact survives only if all of these hold:

1. **The quote is in the text.** After normalising whitespace, non-breaking spaces (French writes "4 500" with one), curly quotes and ligatures, the quote is an exact substring of the fetched text.
2. **It's in the cited article.** When the adapter split the text into articles, the quote must appear in the article the model named. If the split failed for that document, the check falls back to the whole text, and the fact records `article_checked: false`.
3. **The quote is long enough.** At least 20 characters, so the model can't cite "2026".
4. **The numbers match.** Every number in the fact's plain-English statement appears in its quote. "€4,500" matches "4 500 euros", and "7 June 2026" matches "7 June 2026". Month names are translated FR/ES↔EN for this check only.
5. **Headline sentences are backed.** Each "what changed" sentence and the headline list the fact IDs they rely on. A number that isn't in one of those facts fails the check, and the sentence goes back to the lint/regenerate loop.

A dropped fact is removed. If the only fact behind a field is dropped, the field shows "not generated". Dropped facts are counted in `run.counts.facts_dropped` and never shown.

## Writing linter (what it checks)

- the banned terms from the brief, matched whole-word and case-insensitive, including `significantly`;
- em dashes, exclamation marks, rhetorical questions (a sentence ending in `?`) and emoji;
- sentence length: 25 words maximum;
- sentence count: "what changed" is exactly 2 sentences, and every other generated field is exactly 1;
- advice patterns: "should consider", "it is advisable", "companies should" and similar.

On failure, the field is regenerated once with the errors fed back. On a second failure it becomes `"not generated"`.

## Writing examples (reworded to match the Directive)

- ✗ "This significant directive introduces crucial new transparency requirements that organisations will need to navigate in the evolving pay landscape."
- ✓ "EU countries must apply the pay transparency rules by 7 June 2026 (Art. 34). Job applicants get the right to the starting pay or its range, in the ad or before the interview (Art. 5)."

Both sentences are backed by text I checked in the fetched Directive:
- Art. 34(1): "Member States shall bring into force the laws, regulations and administrative provisions necessary to comply with this Directive by 7 June 2026."
- Art. 5(1): "such as in a published job vacancy notice, prior to the job interview or otherwise."

## Configuration: `icp.example.yaml` (shape)

```yaml
icp:
  name: Ledgerly                       # fictional
  description: Payroll and HR software for companies with 10–249 staff in France and Spain.
  markets: [FR, ES]                    # EU acts are always read when the EU source is enabled
  sectors:
    - {nace: "I56", naf: "56", label: "Food and beverage service (hospitality)"}
    - {nace: "I55", naf: "55", label: "Accommodation"}
    - {nace: "G47", naf: "47", label: "Retail trade"}
    - {nace: "F",   naf: "41-43", label: "Construction"}
  size_bands: ["10-49", "50-249"]
  buyer_roles: ["HR manager", "Finance lead"]
  topics: [employment, payroll, pay transparency, training, apprenticeship, social contributions, data protection, tax]

keywords:                              # per language; stems are fine, matching is case/accent-insensitive
  en: [pay, wage, remuneration, employer, worker, apprentice, payroll, social security]
  fr: [rémunération, salaire, employeur, salarié, apprenti, apprentissage, cotisations, paie, "code du travail"]
  es: [salario, retribución, empleador, trabajador, aprendiz, cotización, nómina, "Estatuto de los Trabajadores", "convenio colectivo"]
  exclude: [pêche, pesca, fishing]     # optional hard excludes

sources:
  eu: {enabled: true, eurovoc: ["<ids>"], directory_codes: ["05.20"]}  # codes filled in step 3
  fr: {enabled: true, natures: [LOI, ORDONNANCE, DECRET, ARRETE], exclude_headings: ["Mesures nominatives"]}
  es: {enabled: true, sections: ["1", "3"], materias: ["<codes>"]}      # section 2 always excluded

watch:                                 # optional: directives to track into national law
  directives: ["32023L0970"]

delivery:
  issue: true
  pages: true
  slack: {enabled: false}              # SLACK_WEBHOOK_URL
  email: {enabled: false}              # SMTP_HOST, SMTP_USER, SMTP_PASSWORD, MAIL_TO
  notion: {enabled: false}             # NOTION_TOKEN, NOTION_DATABASE_ID

limits:
  max_documents_per_run: 25
  max_text_chars: 200000               # longer texts: read article by article, or skip with a note
```

`config.py` validates this with a pydantic model and fails fast with a clear message. The ICP comes from `icp.yaml`, or from the `ICP_YAML` environment variable, which the workflow fills from a repository secret.

## `datasets.yaml`: the list-recipe catalogue

This file is new, and I'm proposing it because of the no-invented-facts rule. Three of the five scorecard lines (findable, early, gap evidence) are claims about datasets, not about the law, so the law text can't back them. Left alone, the model would invent datasets or fields.

The catalogue lists public datasets per market, and each entry records its verified facts: publisher, URL, access method, licence, whether it names companies, and which fields exist (for example, a salary field on job ads). The score step may only build recipes from catalogue entries and must cite the entry ID. A recipe that needs a dataset outside the catalogue is allowed, but is labelled `unverified dataset` in the output.

It is ICP-neutral (datasets, not customers), so it doesn't break "all ICP knowledge in one config". Starter entries, each verified before it goes in: France Travail job ads API, the SIRENE company register, Spain's official company register (BORME), and EU-level sources where they exist. The golden test's recipe ("job ads missing a salary range") depends on the France Travail entry.

## JSON schema

One weekly file, `digests/YYYY-WW.json`, validated against `schema/digest.schema.json`. The pydantic models in `models.py` generate that schema, and a test fails if the checked-in file drifts.

### Digest

```jsonc
{
  "schema_version": "1.0",
  "week": "2026-W40",                       // ISO week
  "window": {"since": "2026-09-21", "until": "2026-09-28"},
  "mode": "ai",                             // "ai" | "no-ai"
  "icp": {"name": "Ledgerly", "config_sha256": "…"},
  "nothing_relevant": false,                // true => the md digest is one line
  "entries": [ /* Entry (ai) or NoAiEntry (no-ai), sorted by next deadline, then score */ ],
  "run": {
    "sources": [{"id": "eu", "fetched": 212, "new": 212, "errors": []}],
    "counts": {"fetched": 0, "new": 0, "keyword_pass": 0, "deferred_by_cap": 0,
               "model_pass": 0, "read": 0, "published": 0, "facts_dropped": 0, "fields_not_generated": 0},
    "cost": {"by_model": {"claude-haiku-4-5-20251001": {"input_tokens": 0, "output_tokens": 0},
                          "claude-sonnet-5": {"input_tokens": 0, "output_tokens": 0}},
             "estimated_usd": 0.0, "price_table_date": "YYYY-MM-DD"}
  },
  "disclaimer": "Not legal advice. law-radar flags and summarises official texts; read the source before acting.",
  "attribution": "Sources: EUR-Lex / Publications Office of the EU (CC BY 4.0); DILA, Journal officiel (Licence Ouverte 2.0); Basado en datos de la Agencia Estatal Boletín Oficial del Estado."
}
```

### Entry (one flagged law, AI mode)

```jsonc
{
  "id": "eu:32023L0970",                     // "<source>:<native id>", also the key in seen.json
  "market": "EU",                            // EU | FR | ES
  "doc_type": "Directive",
  "title_original": "Directive (EU) 2023/970 … pay transparency …",
  "language": "en",
  "published": "2023-05-17",
  "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L0970",
  "text_url": "http://publications.europa.eu/resource/celex/32023L0970",
  "text_sha256": "…",                        // hash of the exact text the validator checked
  "transposes": [],                          // for FR/ES entries: CELEX numbers they implement
  "transposed_by": [],                       // filled when a national text on the watchlist appears

  "headline":      {"text": "EU countries must apply pay transparency rules by 7 June 2026.", "fact_refs": ["f1"]},
  "what_changed": [{"text": "…", "fact_refs": ["f1"]}, {"text": "…", "fact_refs": ["f2"]}],
  "who": {
    "text": "Every employer hiring in France or Spain, including Ledgerly's 10–249 staff segment.",
    "icp_match": {"countries": ["FR", "ES"], "sectors": ["all"], "size_bands": ["10-49", "50-249"],
                  "roles": ["HR manager"], "basis": "explicit"},     // explicit | inferred
    "fact_refs": ["f2"]
  },
  "when": {
    "entry_into_force": "2023-06-06",
    "deadlines": [{"date": "2026-06-07", "label": "Transposition deadline", "fact_ref": "f1"}],
    "next_deadline": "2026-06-07"
  },
  "money": {"text": "not generated", "fact_refs": []},   // or: "The text sets no penalty amount; Member States set penalties (Art. 23)."

  "facts": [
    {
      "id": "f1",
      "kind": "date",                        // affected | threshold | date | penalty | amount | obligation
      "statement": "EU countries must transpose the Directive by 7 June 2026.",
      "value": {"date": "2026-06-07", "date_kind": "transposition_deadline"},
      "citation": {
        "article": "Art. 34(1)",
        "quote": "Member States shall bring into force the laws, regulations and administrative provisions necessary to comply with this Directive by 7 June 2026.",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L0970",
        "article_checked": true
      }
    }
    // value shapes: threshold {"metric": "workers", "op": ">=", "value": 100}
    //               amount    {"amount": 4500, "currency": "EUR", "per": "contract, first year"}
  ],

  "scorecard": {
    "forcing_mechanism": {"verdict": "yes", "evidence": "…", "fact_refs": ["f1"]},
    "findable":          {"verdict": "yes", "evidence": "…", "dataset_ids": ["fr_france_travail_offres"]},
    "early":             {"verdict": "yes", "evidence": "…", "dataset_ids": ["…"]},
    "gap_evidence":      {"verdict": "yes", "evidence": "…", "dataset_ids": ["…"]},
    "crowding":          {"verdict": "unclear", "evidence": "…"},
    "points": 9, "max_points": 12,          // computed in code, never by the model
    "sinks": false                           // true when forcing_mechanism is "no"
  },

  "list_recipes": [
    {
      "label": "hypothesis",
      "dataset_id": "fr_france_travail_offres",
      "dataset_verified": true,
      "filter": "NAF 56, companies with 10–249 staff, live ads",
      "gap_evidence": "Ads with no salary field filled",
      "metric": "Live ads without a pay range, per company"
    }
  ],

  "confidence": {"level": "high", "reason": "Every date and threshold comes from an article quoted verbatim."},
  "not_generated": ["money"]
}
```

### NoAiEntry

```jsonc
{"id": "fr:JORFTEXT000053634597", "market": "FR", "doc_type": "DECRET",
 "title_original": "Décret n° 2026-168 du 6 mars 2026 relatif à l'aide exceptionnelle aux employeurs d'apprentis",
 "published": "2026-03-07", "url": "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000053634597",
 "matched_keywords": ["apprenti", "employeur"], "matched_codes": []}
```

### Scoring (computed in code)

yes = 2, unclear = 1, no = 0 on each line, except:
- **crowding** is inverted: "yes, crowded" scores 0;
- **gap evidence** counts double, because it's the strongest signal.

That gives a maximum of 12. If the forcing mechanism is "no", the entry sinks below every entry that has one, whatever its points.

Sort order in the digest and on Pages: entries with a forcing mechanism first, then next deadline (soonest first, laws with no deadline last), then points.

## Markdown digest (one entry)

```markdown
### EU countries must apply pay transparency rules by 7 June 2026.
**EU** · Directive (EU) 2023/970 · confidence: high

**What changed:** … (2 sentences)
**Who:** …
**When:** transposition deadline 7 June 2026 (Art. 34)
**Penalty / money at stake:** not generated
**Scorecard (9/12):** forcing mechanism yes · findable yes · early yes · gap evidence yes · crowding unclear
**List recipes (hypotheses):**
1. France Travail job ads · NAF 56, 10–249 staff · no salary field · number = live ads without a range
**Sources:** [Art. 34(1)](…) "Member States shall bring into force…" · [Art. 5(1)](…) "…"
```

An empty week is one line: `Law radar, week 40: nothing relevant this week.`, followed by the disclaimer.

## Dependencies (need your approval)

| Package | Why | Notes |
|---|---|---|
| `anthropic` | Claude API | It already pulls in `httpx` and `pydantic`, which I'd use for HTTP and the models, so no extra packages for those |
| `pyyaml` | read `icp.yaml` and `datasets.yaml` | |
| `pytest` (dev only) | tests | |

Everything else uses the standard library: XML parsing (`xml.etree`), `tarfile` for the DILA dumps, `smtplib`, and HTML generation. The Issue uses the `gh` CLI that comes with GitHub's runners. Pages uses GitHub's official actions. There's no paid service anywhere.

## Open points for you

1. **Repo licence:** I propose MIT for the code. Source texts keep their own licences, credited in every digest.
2. **The `datasets.yaml` catalogue:** is it OK to add it as described?
3. **Scoring weights:** yes=2 / unclear=1 / no=0, crowding inverted, gap evidence ×2.
4. **Recording model responses for the tests:** that needs one real run with `ANTHROPIC_API_KEY` on your machine, over three fixture documents. I'll check current prices in step 3 and give you the estimate before spending anything.
5. **The €5,000 "aide unique" figure** for the README limitation: I'll check it against the official text before it goes in. If I can't find it there, the README states the limitation without that number.
