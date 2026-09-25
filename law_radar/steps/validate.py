"""Citation validator. Facts that fail are dropped, never softened.

A fact survives only if:
1. its quote is an exact substring of the fetched text (after canon());
2. the quote sits in the article the model cited (when the text was split into articles);
3. the quote is at least MIN_QUOTE_CHARS long;
4. every number and month in the statement (and the date value) appears in the quote.

Sentences built on facts (headline, what changed, who, money, scorecard evidence) are checked
with check_sentence(): every fact they cite must have survived, and every number or month they
assert must appear in those facts' quotes.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..models import Citation, Document, Fact, FactOut
from ..textnorm import canon, months, quote_numbers, statement_numbers

MIN_QUOTE_CHARS = 20

# Principle 5: the tool reads laws, never people. A quote that names a person with a courtesy title
# (common in Spanish collective-agreement minutes and French appointment texts) is dropped.
_PERSON = re.compile(r"(?:\b(?:don|doña|dña\.|Mme|Mlle)|\bD\.ª|\bM\.)\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+")

_ARTICLE_WORDS = r"(?:art(?:icle|ículo|iculo)?s?\.?|§)"
_ORDINALS = {"premier": "1", "1er": "1", "primero": "1", "unique": "unique", "unico": "unique", "único": "unique"}


def parse_article_ref(ref: str) -> Tuple[str, Optional[str]]:
    """Return (kind, number). kind is article | annex | recital | other."""
    r = ref.strip().lower()
    if re.match(r"(annex|annexe|anexo)\b", r):
        return "annex", None
    if re.match(r"(recital|considérant|considerando)\b", r):
        return "recital", None
    m = re.match(_ARTICLE_WORDS + r"\s*(premier|1er|unique|único|unico|primero|[0-9]+(?:\s*(?:bis|ter|quater))?[a-z]?)", r)
    if m:
        num = m.group(1).replace(" ", "")
        return "article", _ORDINALS.get(num, num)
    m = re.match(r"([0-9]+[a-z]?)\b", r)
    if m:
        return "article", m.group(1)
    return "other", None


def _normalise_num(num: str) -> str:
    n = num.strip().lower().replace(" ", "")
    return _ORDINALS.get(n, n)


def _article_texts(doc: Document, num: str) -> List[str]:
    """Every article with that number. A number can repeat, for example in a Spanish resolution
    that quotes the clauses of a collective agreement. A quote must sit inside one of them."""
    return [art.text for art in doc.articles if _normalise_num(art.num) == num]


def _date_supported(value: dt.date, quote: str) -> bool:
    nums = quote_numbers(quote)
    return str(value.year) in nums and str(value.day) in nums and value.month in months(quote)


def check_fact(doc: Document, fact: FactOut) -> Tuple[Optional[Fact], Optional[str]]:
    """Return (Fact, None) when valid, or (None, reason) when dropped."""
    quote = fact.citation.quote.strip()
    cq = canon(quote)
    if len(cq) < MIN_QUOTE_CHARS:
        return None, f"quote shorter than {MIN_QUOTE_CHARS} characters"
    if cq not in canon(doc.text):
        return None, "quote not found in the fetched text"
    if _PERSON.search(cq):
        return None, "quote names a person"

    kind, num = parse_article_ref(fact.citation.article)
    article_checked = False
    if doc.articles and kind == "article" and num:
        art_texts = _article_texts(doc, num)
        if not art_texts:
            return None, f"cited article {fact.citation.article!r} not found"
        if not any(cq in canon(t) for t in art_texts):
            return None, f"quote not in cited article {fact.citation.article!r}"
        article_checked = True

    missing = statement_numbers(fact.statement) - quote_numbers(quote)
    if missing:
        return None, f"numbers not in quote: {sorted(missing)}"
    missing_months = months(fact.statement) - months(quote)
    if missing_months:
        return None, f"months not in quote: {sorted(missing_months)}"

    date_value = None
    if fact.date:
        try:
            date_value = dt.date.fromisoformat(fact.date)
        except ValueError:
            return None, f"invalid date {fact.date!r}"
        if not _date_supported(date_value, quote):
            return None, f"date {fact.date} not in quote"

    return Fact(
        id=fact.id,
        kind=fact.kind,
        statement=fact.statement.strip(),
        date=date_value,
        date_kind=fact.date_kind if date_value else None,
        citation=Citation(article=fact.citation.article.strip(), quote=quote, url=doc.url,
                          article_checked=article_checked),
    ), None


def validate_facts(doc: Document, facts: Iterable[FactOut]) -> Tuple[List[Fact], List[Tuple[str, str]]]:
    kept: List[Fact] = []
    dropped: List[Tuple[str, str]] = []
    seen_ids: Set[str] = set()
    for f in facts:
        if f.id in seen_ids:
            dropped.append((f.id, "duplicate fact id"))
            continue
        seen_ids.add(f.id)
        fact, reason = check_fact(doc, f)
        if fact:
            kept.append(fact)
        else:
            dropped.append((f.id, reason or "invalid"))
    return kept, dropped


def check_sentence(text: str, fact_refs: List[str], facts: Dict[str, Fact],
                   extra_numbers: Optional[Set[str]] = None, require_refs: bool = False) -> List[str]:
    """Errors for a sentence that relies on facts. Empty list means it passes."""
    errors: List[str] = []
    unknown = [r for r in fact_refs if r not in facts]
    if unknown:
        errors.append(f"relies on facts that were dropped or don't exist: {unknown}")
    if require_refs and not fact_refs:
        errors.append("cites no fact")
    quotes = " ".join(facts[r].citation.quote for r in fact_refs if r in facts)
    allowed = quote_numbers(quotes) | (extra_numbers or set())
    missing = statement_numbers(text) - allowed
    if missing:
        errors.append(f"numbers not backed by cited facts: {sorted(missing)}")
    missing_months = months(text) - months(quotes)
    if missing_months:
        errors.append(f"months not backed by cited facts: {sorted(missing_months)}")
    return errors
