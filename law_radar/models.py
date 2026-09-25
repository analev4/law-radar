"""Data models. These pydantic classes are the single source of the JSON schema.

Three groups:
- Document: what a source adapter returns.
- *Output models: what the model is asked to return (sent as a JSON schema).
- Digest / Entry: what gets published.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

Verdict = Literal["yes", "no", "unclear"]
FactKind = Literal["affected", "threshold", "date", "penalty", "amount", "obligation"]
DateKind = Literal["publication", "entry_into_force", "deadline", "transposition_deadline", "application"]


# ---------------------------------------------------------------------------
# Source documents
# ---------------------------------------------------------------------------

class Article(BaseModel):
    num: str                      # normalised article number: "5", "34", "1", "unique"
    heading: Optional[str] = None
    text: str


class Document(BaseModel):
    id: str                       # "<source>:<native id>", e.g. "eu:32023L0970"
    source: str                   # eu | fr | es
    market: str                   # EU | FR | ES
    native_id: str
    title: str
    language: str                 # en | fr | es
    doc_type: str
    published: dt.date
    entry_into_force: Optional[dt.date] = None
    url: str                      # link shown to readers
    text_url: str                 # where the text is fetched from
    classification: Dict[str, List[str]] = Field(default_factory=dict)
    transposes: List[str] = Field(default_factory=list)   # CELEX numbers
    articles: List[Article] = Field(default_factory=list)
    text: str = ""                # full normalised text, empty until fetched


# ---------------------------------------------------------------------------
# What the model returns (strict JSON schemas are generated from these)
# ---------------------------------------------------------------------------

class FilterOutput(BaseModel):
    relevant: bool
    reason: str


class CitationOut(BaseModel):
    article: str                  # "Art. 34(1)", "Article 1", "Artículo 5"
    quote: str                    # verbatim, contiguous, from the supplied text


class FactOut(BaseModel):
    id: str                       # f1, f2, ...
    kind: FactKind
    statement: str                # one plain-English sentence
    date: Optional[str]           # ISO date when kind == "date"
    date_kind: Optional[DateKind]
    citation: CitationOut


class SentenceOut(BaseModel):
    text: str
    fact_refs: List[str]


class IcpMatch(BaseModel):
    countries: List[str]
    sectors: List[str]
    size_bands: List[str]
    roles: List[str]
    basis: Literal["explicit", "inferred"]


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    reason: str


class ReadOutput(BaseModel):
    headline: SentenceOut
    what_changed: List[SentenceOut]
    who: SentenceOut
    icp_match: IcpMatch
    money: SentenceOut
    facts: List[FactOut]
    transposes: List[str]         # CELEX numbers of EU directives this text implements
    confidence: Confidence


class ScoreLineOut(BaseModel):
    verdict: Verdict
    evidence: str
    fact_refs: List[str]
    dataset_ids: List[str]


class RecipeOut(BaseModel):
    dataset_id: str
    filter: str
    gap_evidence: str
    metric: str
    signal_strength: Literal["strong", "weak"]
    caveat: Optional[str]


class ScoreOutput(BaseModel):
    forcing_mechanism: ScoreLineOut
    findable: ScoreLineOut
    early: ScoreLineOut
    gap_evidence: ScoreLineOut
    crowding: ScoreLineOut
    list_recipes: List[RecipeOut]


class RewriteOutput(BaseModel):
    text: str
    fact_refs: List[str]          # the validated facts the rewritten text relies on


# ---------------------------------------------------------------------------
# Published digest
# ---------------------------------------------------------------------------

NOT_GENERATED = "not generated"


class Citation(BaseModel):
    article: str
    quote: str
    url: str
    article_checked: bool


class Fact(BaseModel):
    id: str
    kind: FactKind
    statement: str
    date: Optional[dt.date] = None
    date_kind: Optional[DateKind] = None
    citation: Citation


class Sentence(BaseModel):
    text: str
    fact_refs: List[str] = Field(default_factory=list)


class Who(Sentence):
    icp_match: Optional[IcpMatch] = None


class Deadline(BaseModel):
    date: dt.date
    label: str
    fact_ref: str


class When(BaseModel):
    publication: dt.date
    entry_into_force: Optional[dt.date] = None
    deadlines: List[Deadline] = Field(default_factory=list)
    next_deadline: Optional[dt.date] = None


class ScoreLine(BaseModel):
    verdict: Verdict
    evidence: str
    fact_refs: List[str] = Field(default_factory=list)
    dataset_ids: List[str] = Field(default_factory=list)


class Scorecard(BaseModel):
    forcing_mechanism: ScoreLine
    findable: ScoreLine
    early: ScoreLine
    gap_evidence: ScoreLine
    crowding: ScoreLine
    points: int
    max_points: int
    sinks: bool


class ListRecipe(BaseModel):
    label: Literal["hypothesis"] = "hypothesis"
    dataset_id: str
    dataset_name: str
    dataset_url: Optional[str] = None
    dataset_verified: bool
    filter: str
    gap_evidence: str
    metric: str
    signal_strength: Literal["strong", "weak"]
    caveat: Optional[str] = None


class Entry(BaseModel):
    kind: Literal["ai"] = "ai"
    id: str
    market: str
    doc_type: str
    title_original: str
    language: str
    published: dt.date
    url: str
    text_url: str
    text_sha256: str
    transposes: List[str] = Field(default_factory=list)
    headline: Sentence
    what_changed: List[Sentence]
    who: Who
    when: When
    money: Sentence
    facts: List[Fact]
    scorecard: Optional[Scorecard] = None
    list_recipes: List[ListRecipe] = Field(default_factory=list)
    confidence: Confidence
    not_generated: List[str] = Field(default_factory=list)


class NoAiEntry(BaseModel):
    kind: Literal["no-ai"] = "no-ai"
    id: str
    market: str
    doc_type: str
    title_original: str
    published: dt.date
    url: str
    matched_keywords: List[str] = Field(default_factory=list)
    matched_codes: List[str] = Field(default_factory=list)


class SourceReport(BaseModel):
    id: str
    fetched: int = 0
    new: int = 0
    errors: List[str] = Field(default_factory=list)


class Counts(BaseModel):
    fetched: int = 0
    new: int = 0
    keyword_pass: int = 0
    deferred_by_cap: int = 0
    model_pass: int = 0
    read: int = 0
    published: int = 0
    facts_dropped: int = 0
    fields_not_generated: int = 0


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class Cost(BaseModel):
    by_model: Dict[str, ModelUsage] = Field(default_factory=dict)
    estimated_usd: float = 0.0
    price_table_date: str = ""


class RunInfo(BaseModel):
    sources: List[SourceReport] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)
    cost: Cost = Field(default_factory=Cost)


class Window(BaseModel):
    since: dt.date
    until: dt.date


class IcpRef(BaseModel):
    name: str
    config_sha256: str


DISCLAIMER = (
    "Not legal advice. law-radar flags and summarises official texts. "
    "Read the source before acting."
)
ATTRIBUTION = (
    "Sources: EUR-Lex / Publications Office of the EU (CC BY 4.0); "
    "DILA, Journal officiel (Licence Ouverte 2.0); "
    "Basado en datos de la Agencia Estatal Boletín Oficial del Estado."
)


class Digest(BaseModel):
    schema_version: str = SCHEMA_VERSION
    week: str                     # ISO week, "2026-W40"
    window: Window
    mode: Literal["ai", "no-ai"]
    # Who wrote the AI fields: Claude Code (/digest), the Claude API, or saved answers replayed in tests.
    generated_by: Literal["no-ai", "claude-code", "api", "replay"] = "no-ai"
    icp: IcpRef
    nothing_relevant: bool
    entries: List[Union[Entry, NoAiEntry]] = Field(default_factory=list)
    run: RunInfo = Field(default_factory=RunInfo)
    disclaimer: str = DISCLAIMER
    attribution: str = ATTRIBUTION
