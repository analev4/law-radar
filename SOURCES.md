# Sources

law-radar reads only official journals. This file records how each one is accessed, what it costs, what limits apply and under which licence the text may be reused.

Last verified: 24 September 2026, with live requests from a plain `curl` client. "Verified" below means we made the request and got the stated result. Anything we could not confirm from the publisher's own page is marked **unverified**.

| Source | Access method | Credentials | Rate limit | Licence |
|---|---|---|---|---|
| EU Official Journal (L series) | Cellar SPARQL for the list, Cellar REST for the text | None | None published | CC BY 4.0 (Decision 2011/833/EU) |
| France, Journal officiel | DILA open data dumps (`JORF/`), twice daily | None | None published | Licence Ouverte / etalab-2.0 |
| Spain, BOE | BOE open data API (daily summary) plus per-item XML | None | None published | BOE reuse conditions (commercial use allowed, attribution required) |

None of the three v1 sources needs an API key. The only secret the pipeline needs is `ANTHROPIC_API_KEY`, and `--no-ai` mode needs none.

---

## EU: Official Journal, L series

### What we use

1. **List new acts:** the Cellar SPARQL endpoint, `https://publications.europa.eu/webapi/rdf/sparql` (GET, `query=` and `format=application/sparql-results+json`).
   Since October 2023 the OJ L series is published act by act, so there is no "issue" to download. We select acts in the OJ-L collection by publication date:

   ```sparql
   PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
   SELECT DISTINCT ?work ?celex ?pub ?eli WHERE {
     ?work cdm:official-journal-act_part_of_collection_document
             <http://publications.europa.eu/resource/authority/document-collection/OJ-L> ;
           cdm:official-journal-act_date_publication ?pub ;
           cdm:resource_legal_id_celex ?celex .
     OPTIONAL { ?work cdm:resource_legal_eli ?eli }
     FILTER(?pub >= "2026-09-21"^^<http://www.w3.org/2001/XMLSchema#date>)
   } ORDER BY ?pub
   ```

   Verified: this returned the acts published on 21 September 2026 (for example `32026R2105`, ELI `http://data.europa.eu/eli/reg_impl/2026/2105/oj`).

   Acts published before October 2023 belonged to an OJ issue and have no `official-journal-act_date_publication`, so this query doesn't find them. That doesn't matter for weekly runs. The golden fixture for Directive 2023/970 therefore stores its metadata from the Directive's own Cellar record (OJ L 132 of 17 May 2023, in force 6 June 2023).

2. **Metadata per act** (same endpoint): title (`cdm:work_title`), type (`cdm:resource_legal_type`: R, L, D…), entry into force (`cdm:resource_legal_date_entry-into-force`), EuroVoc concepts (`cdm:work_is_about_concept_eurovoc`), directory code (`cdm:resource_legal_is_about_concept_directory-code`), subject matter. These give the classification codes the cheap filter uses.

3. **Full text:** Cellar content negotiation on the CELEX URI.

   ```
   GET http://publications.europa.eu/resource/celex/{CELEX}
   Accept: application/xhtml+xml
   Accept-Language: eng
   ```

   Verified: `32023L0970` (Pay Transparency Directive) returned 194 KB of XHTML, and the text contains Article 5 ("Pay transparency prior to employment"), the date "7 June 2026" and "at least 100 workers". A recent act (`32026R2104`) also returned its XHTML. Other languages work by changing `Accept-Language` (`fra`, `spa`).

4. **Link shown to readers:** the ELI (`http://data.europa.eu/eli/...`) or the EUR-Lex page `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{CELEX}`.

### What we do not use, and why

- **EUR-Lex HTML pages** (`eur-lex.europa.eu/legal-content/...`): verified to return `HTTP 202` with an empty body and the header `x-amzn-waf-action: challenge`. That is an AWS WAF bot check. law-radar does not try to get past bot checks. We link to EUR-Lex for humans and fetch the same text from Cellar.
- **EUR-Lex SOAP web service:** needs a registered account and returns search results, not anything Cellar lacks. Not needed.
- **OJ RSS feeds:** Cellar gives the same list with structured metadata.

### Limits and licence

- **Auth:** none. The Publications Office describes the SPARQL interface as publicly accessible ([Cellar knowledge graph](https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph)).
- **Rate limits:** none published. A third-party guide reports a 60-second query timeout (**unverified** from an official page). We keep queries narrow (one date window, `LIMIT`/`OFFSET` paging), send about one request per second, and set a `User-Agent` that names the project.
- **Licence:** EU documents are reusable under [Commission Decision 2011/833/EU](https://op.europa.eu/en/publication-detail/-/publication/cb76d4a0-c886-40bd-99d7-8db018a723d0/language-en), which the Commission implements as CC BY 4.0 ([Commission legal notice](https://commission.europa.eu/legal-notice_en)). Attribution and a note of changes are required. Only the OJ published on EUR-Lex is legally authentic, so every digest links back to it.

---

## France: Journal officiel (JORF, "Lois et décrets" edition)

### What we use

**DILA open data dumps**, `https://echanges.dila.gouv.fr/OPENDATA/JORF/`.

- Verified: the directory lists incremental archives named `JORF_YYYYMMDD-HHMMSS.tar.gz`, usually two a day (one after midnight and one in the evening, 0.1–9 MB each). 491 archives were listed for 2026 so far. A full base (`Freemium_jorf_global_20250713-140000.tar.gz`) is also there, but we don't need it.
- Fetch rule: download every archive whose timestamp is later than the last run, and nothing else.
- Inside each archive (verified on `JORF_20260922-214912.tar.gz`, 26,146 files):
  - `jorf/global/texte/version/.../JORFTEXT*.xml`: text metadata, including `NATURE` (LOI, DECRET, ARRETE, ORDONNANCE…), `NUM`, `NOR`, `DATE_PUBLI`, `DATE_TEXTE`, `TITREFULL`, `MINISTERE`, ELI.
  - `jorf/global/texte/struct/.../JORFTEXT*.xml`: the list of articles (`LIEN_ART id=… num=…`).
  - `jorf/global/article/.../JORFARTI*.xml`: article text in `<CONTENU>`.
  - `jorf/global/conteneur/...`: the issue's table of contents, with the ministry and heading for each text.
- **Important:** the archives also contain corrections to old records (the same archive held a container from January 2016 and a decree from 2024). We keep a text only if its `DATE_PUBLI` falls inside the run window. In that archive, 39 of 44 text versions had `DATE_PUBLI` 2026-09-22.
- **Link shown to readers:** `https://www.legifrance.gouv.fr/jorf/id/{JORFTEXT…}`. Légifrance returns `HTTP 403` to `curl`, so it serves as the human link only. The citation validator checks quotes against the DILA text, which is the same text.

Verified end to end on the golden fixture: `JORF_20260307-002619.tar.gz` contains **Décret n° 2026-168 du 6 mars 2026 relatif à l'aide exceptionnelle aux employeurs d'apprentis** (`JORFTEXT000053634597`, NOR `TRSD2535889D`, published 7 March 2026). Article 1 contains the amounts: "4 500 euros maximum", "2 000 euros maximum", "1 500 euros maximum", "750 euros maximum", and "6 000 euros maximum" for apprentices with a recognised disability. Contracts must start before 1 January 2027. Article 2 applies the decree to contracts signed from the day after publication.

### Alternative: Légifrance API via PISTE (not used by default)

- Free, but needs an account on [PISTE](https://piste.gouv.fr), acceptance of the API terms ("Consentement CGU API"), and an application with the Légifrance API enabled.
- OAuth 2.0 client credentials. Tokens last 3,600 seconds.
  - Sandbox: token `https://sandbox-oauth.piste.gouv.fr/api/oauth/token`, API `https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app`
  - Production: token `https://oauth.piste.gouv.fr/api/oauth/token`, API `https://api.piste.gouv.fr/dila/legifrance/lf-engine-app`
- Quotas apply per application or per token and are shown in the PISTE "Applications" tab. The figures are not public (**unverified**).
- Source: [Légifrance API FAQ](https://www.legifrance.gouv.fr/contenu/pied-de-page/foire-aux-questions-api), [API terms (PDF)](https://www.legifrance.gouv.fr/contenu/Media/files/pied-de-page/cgu-legifrance-api-vf-15-12-2022_0.pdf).
- If someone wants it later, the adapter would read `LEGIFRANCE_CLIENT_ID` and `LEGIFRANCE_CLIENT_SECRET` from environment variables. **Recommendation: skip it for v1.** The DILA dumps carry the same texts with no registration, which keeps setup at "add one API key".

### Limits and licence

- **Auth:** none for the dumps.
- **Rate limits:** none published. A normal week is about 14 archives (roughly 30–60 MB), downloaded once.
- **Licence:** Licence Ouverte / Open Licence, now etalab-2.0 ([data.gouv.fr dataset](https://www.data.gouv.fr/fr/datasets/jorf-les-donnees-de-l-edition-lois-et-decrets-du-journal-officiel/)). Commercial reuse is allowed. Attribution must name the source (DILA) and the date of last update.
- **Personal data:** DILA already withholds the content of sensitive individual acts. A naturalisation decree appears with its title and a note that it is "Accès protégé". Appointments and other nominative measures are published in full. law-radar drops every text filed under "Mesures nominatives" or "Naturalisations" in the issue's table of contents before anything reads it (Principle 5).
- **As built (step 4):** `sources/fr_dila.py` downloads the archives dated from the day before the window to the day after, and keeps texts whose `DATE_PUBLI` is inside the window and whose nature is in the config (LOI, ORDONNANCE, DECRET, ARRETE). It rebuilds each text as title, notice, visas, then the articles in order, following `LIEN_SECTION_TA` into sections. A live run for 18–24 September 2026 downloaded 40 MB of archives and returned 141 French texts. A national text that says it transposes an EU directive gets that directive's CELEX number in `transposes`. On this week's data that found Décret n° 2026-883, which transposes Directive (EU) 2019/882.

---

## Spain: Boletín Oficial del Estado (BOE)

### What we use

1. **Daily summary:** `GET https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD}` with `Accept: application/json` (XML is also available).
   Verified for 23 September 2026: 153 items across sections `1, 2A, 2B, 3, 5A, 5B, 5C`. Each item has `identificador` (for example `BOE-A-2026-19695`), `titulo`, `url_pdf`, `url_html` and `url_xml`, grouped by section and ministry (`departamento`). There is no BOE on Sundays, so the fetch loops over each date in the window and skips days that return nothing.
2. **Full text and metadata per item:** `GET https://www.boe.es/diario_boe/xml.php?id={identificador}`.
   Verified: it returns `rango` (Ley, Real Decreto, Orden…), `fecha_publicacion`, `fecha_vigencia` (entry into force), ELI, subject codes (`<materias>`, for example `codigo="200"` Alimentación), and the full text in `<texto>`, with articles marked `<p class="articulo">`.
3. **Link shown to readers:** `url_html` (`https://www.boe.es/diario_boe/txt.php?id=…`) or the ELI.

Sections we read by default:
- **1, Disposiciones generales:** laws, royal decrees and orders. This is the main target.
- **3, Otras disposiciones:** only under the epigraphs listed in the config. The default is "Convenios colectivos de trabajo" (collective agreements), which matter for payroll ICPs. The rest of section 3 is grants, prizes, curricula and similar acts.
- **Never read:** section 2 (Autoridades y personal: appointments of named people). It is blocked in code, whatever the config says. Sections 4 and 5 (courts, announcements) aren't read either.

**Personal data in collective agreements.** Agreement minutes can name the members of the negotiating committee. On 19 February 2026, BOE-A-2026-3870 did. law-radar never stores those texts in the repo; they stay in the local, gitignored `.cache`. The read prompt forbids quoting a passage that names a person, and the citation validator drops any quote that names someone with a courtesy title ("don", "doña", "M.", "Mme"). The golden fixtures don't include that agreement, and the one appointment kept to test the section 2 exclusion has the person's name removed.

**As built (step 4):** `sources/es_boe.py` fetches one summary per day in the window (404 means no BOE that day), then the XML of each item it keeps. A live run for 19–22 September 2026 fetched 21 texts in 25 seconds. Articles are split on `<p class="articulo">`. "Disposición" blocks stay in the full text but aren't articles, so a quote from a final provision is checked against the whole text. Example config subject codes: 1667, 1684, 1754, 2490, 3160, 3805, 4553, 4662, 6047, 6230, 6256, 6257, 6499, 6909 (from `/datosabiertos/api/datos-auxiliares/materias`).

The same API also serves consolidated legislation (`/datosabiertos/api/legislacion-consolidada/...`) and subject lookup tables (`/datosabiertos/api/datos-auxiliares/materias`), which the config can use to map subject codes to labels. Source: [BOE open data API](https://www.boe.es/datosabiertos/api/api.php).

### Limits and licence

- **Auth:** none.
- **Rate limits:** none published. The BOE keeps the right to suspend access without notice for anyone who breaks the reuse terms. `robots.txt` only blocks translated-language views of `txt.php`, which we don't use.
- **Licence:** [BOE reuse conditions](https://www.boe.es/informacion/aviso_legal/index.php#reutilizacion). Commercial and non-commercial reuse are allowed. Conditions: cite the source with a link to boe.es ("Basado en datos de la Agencia Estatal Boletín Oficial del Estado" for derived works), don't change the meaning, don't imply official endorsement, keep the update date, and flag modifications. Every digest carries this line.

---

## How the pipeline treats all sources

- **Polite client:** one shared HTTP client, about one request per second per host, a `User-Agent` of `law-radar/<version> (+<repo URL>)`, retries with backoff on 429 and 5xx, and no retry on 403 or WAF challenges (these are logged and skipped).
- **No bot-check workarounds:** no headless browser and no stealth plugins. If a publisher blocks automated access, we use their open data channel or drop the source.
- **Stored text:** the fetched text is cached per run so the citation validator checks quotes against exactly what the model read. `state/seen.json` stores IDs only (CELEX, JORFTEXT, BOE-A), never text or names.
- **Attribution footer** on every digest: "Sources: EUR-Lex / Publications Office of the EU (CC BY 4.0); DILA, Journal officiel (Licence Ouverte 2.0); Basado en datos de la Agencia Estatal Boletín Oficial del Estado."

## Adding a source

Candidates for later, all with official open data: Germany (`recht.bund.de`, Bundesgesetzblatt), Italy (Gazzetta Ufficiale), Portugal (Diário da República). Each needs the same checks as above before any code is written. See `CONTRIBUTING.md` (to be written).
