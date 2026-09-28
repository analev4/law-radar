# Contributing

Thanks for helping. This file covers the developer setup, the tests and their recorded answers, how to add a source, and how to add a dataset. Design decisions and their history are in [DESIGN.md](DESIGN.md). How each source is accessed and licensed is in [SOURCES.md](SOURCES.md).

## Setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

```bash
.venv/bin/pytest -q
```

Python 3.9 or newer. The default install has no API dependency. Add `.[api]` only if you want the optional Claude API mode.

A free run on real data, with no model calls:

```bash
.venv/bin/law-radar run --no-ai --config icp.example.yaml --since 2026-09-21 --out /tmp/digests --state /tmp/state
```

## How the code is laid out

```
law_radar/
  sources/     one adapter per journal (eu_cellar, fr_dila, es_boe), plus shared helpers
  steps/       keyword filter, model filter, read, validate, lint, score, assemble
  prompts/     style.md (writing rules, shared) and one prompt per model step
  publish/     Markdown and JSON digests, the Issue, the Pages table, optional channels
  datasets/    company-only exports of catalogue datasets (bdns.py)
  llm.py       where model answers come from: exchange (Claude Code), replay (tests), API
  pipeline.py  fetch, dedupe, filter, read, score, publish
```

## Tests and recorded answers

CI runs `pytest` on every push, with no API key. Model answers are replayed from `tests/fixtures/recorded/`.

The golden tests run three real texts through the whole pipeline: the EU Pay Transparency Directive, the French apprentice-aid decree and the Spanish minimum-wage decree. An EU fisheries regulation checks that irrelevant texts are rejected. Their answers were written in Claude Code, not through the API:

```bash
.venv/bin/law-radar record-fixtures
```

This writes one request file per model call under `.cache/record/pending/` and stops. Answer each request with a fresh Claude Code subagent that reads only that file. Use the prompt in `.claude/skills/digest/SKILL.md`, and keep the subagent away from the tests, so it can't steer answers towards passing. Run the command again until it prints `COMPLETE`.

Every recording stores a fingerprint of its request. If you change a prompt, the ICP example or a fixture, replay fails with "stale recording". Delete the recordings and record again. Never edit a recorded answer by hand.

`--api` records through the Claude API instead, if you have a key.

## Writing a source adapter

A source is one journal. An adapter turns it into `Document` objects and knows nothing about the ICP, the model or the digest.

### 1. Check the source first

Before writing code, add a section to [SOURCES.md](SOURCES.md) with the following, each checked with a real request:

- the access method (API, bulk files, feed), with URLs;
- authentication, and how to get credentials (read them from environment variables);
- rate limits or fair-use rules;
- the reuse licence and the attribution it requires;
- which sections name people, and how you'll exclude them.

Primary sources only: the official journal or legislation database, never a news site or a law firm. If the publisher blocks automated access, use its open-data channel, or don't add the source. law-radar never works around bot checks.

### 2. Implement the interface

```python
class Source(Protocol):
    id: str        # "de"
    market: str    # "DE"

    def fetch_since(self, since: date, until: date) -> list[Document]: ...
    def fetch_text(self, doc: Document) -> Document: ...
```

`fetch_since` returns everything published in the window, with metadata. The text can be left empty if fetching it costs one request per document; `fetch_text` fills it in later, only for keyword matches. Use the shared `PoliteClient` (`law_radar/http.py`): one request per second per host, a named user agent, backoff on 429 and 5xx, and no retry on a block.

Fill these `Document` fields:

| Field | Notes |
|---|---|
| `id` | `"<source id>:<native id>"`, stable across runs. It is the key in `state/seen.json`. |
| `title`, `language`, `doc_type`, `published` | From the source's metadata. `language` selects the keyword list. |
| `url` | The page a person should open. |
| `text_url` | Where the text was fetched from. |
| `classification` | The source's own codes and labels. Keys ending in `_labels`, plus `headings` and `department`, are searched by the keyword filter. |
| `articles` | One `Article(num, text)` per article, so the validator can check that a quote sits in the article cited. Leave it empty if the source doesn't mark articles; quotes are then checked against the whole text. |
| `text` | The full text, cleaned with `textnorm.clean`. |
| `transposes` | `transposed_directives(text)` from `sources/transpose.py`. |

Exclude sections that name people inside the adapter, before anything else sees them. France drops "Mesures nominatives" and "Naturalisations"; Spain never reads BOE section 2.

### 3. Wire it in

- Add a config block for the source in `config.py` (`enabled`, plus any codes or sections) and to `icp.example.yaml`.
- If the source has classification codes worth matching, add them to `code_matches` in `steps/keyword_filter.py`.
- Register the adapter in `build_sources` in `cli.py`.
- Add the attribution line to `models.ATTRIBUTION` and the README.

### 4. Test it on real bytes

- Save a trimmed copy of a real payload under `tests/fixtures/<source>/`. Keep only the files you need, and remove any person's name from them.
- Test the parser: metadata, article split, the exclusion of sections that name people, and the date window.
- Test the keyword filter on one relevant and one irrelevant text.
- If you add a golden text, add its expectations to `tests/test_golden.py` and record its answers as described above.

## Adding a dataset to the catalogue

List recipes may only use datasets in [`datasets.yaml`](datasets.yaml); anything else is shown as "unverified dataset". Before adding one:

- Check its access, fields and licence on the publisher's own pages, and fill in `verified_on` and `verified` with what you checked and how.
- Company-level data only. If the dataset also names people, strip them in code before anything is stored (see `law_radar/datasets/bdns.py`, which keeps legal-entity tax IDs only), and add a test with made-up records.
- Note in `notes` what the dataset can't tell you, such as company size or sector.

## Writing rules

Every model-written sentence is linted (`steps/lint.py`): banned filler words, 25 words at most, one sentence per field, no advice, no em dashes, no exclamation marks, no questions, no emoji. Try a sentence:

```bash
.venv/bin/law-radar lint "Employers must publish the pay range from 7 June 2026."
```
