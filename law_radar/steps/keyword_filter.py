"""Cheap filter: keywords and each source's own classification codes. Plain code, no model."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from ..config import Config
from ..models import Document
from ..textnorm import strip_accents

# Documents whose type sorts first when the cost cap bites.
TYPE_RANK = {"loi": 0, "ley": 0, "directive": 0, "regulation": 1, "ordonnance": 1, "real decreto": 1,
             "decret": 1, "décret": 1, "decision": 3, "arrete": 3, "arrêté": 3, "orden": 3}


@dataclass
class Match:
    doc: Document
    keywords: List[str] = field(default_factory=list)
    codes: List[str] = field(default_factory=list)
    watched: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.keywords or self.codes or self.watched)


def _norm(text: str) -> str:
    return strip_accents(text).lower()


def _compile(keyword: str) -> re.Pattern:
    kw = _norm(keyword.strip())
    if kw.endswith("*"):
        return re.compile(r"(?<!\w)" + re.escape(kw[:-1]))
    return re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)")


def searchable_text(doc: Document) -> str:
    parts = [doc.title]
    for key, values in doc.classification.items():
        if key.endswith("_labels") or key in ("headings", "department"):
            parts.extend(values)
    return _norm(" | ".join(parts))


def code_matches(doc: Document, cfg: Config) -> List[str]:
    hits: List[str] = []
    if doc.source == "eu":
        eu = cfg.sources.eu
        for code in doc.classification.get("directory", []):
            if any(code.startswith(p) for p in eu.directory_prefixes):
                hits.append(f"directory:{code}")
        for ev in doc.classification.get("eurovoc", []):
            if ev in eu.eurovoc:
                hits.append(f"eurovoc:{ev}")
    elif doc.source == "es":
        wanted = set(cfg.sources.es.materias)
        hits.extend(f"materia:{c}" for c in doc.classification.get("materias", []) if c in wanted)
    return hits


class KeywordFilter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # Keywords apply to texts in their own language only ("nómina*" must not hit French "nomination").
        self.include: Dict[str, List[Tuple[str, re.Pattern]]] = {
            lang: [(kw, _compile(kw)) for kw in kws] for lang, kws in cfg.keywords.items() if lang != "exclude"
        }
        self.exclude: List[Tuple[str, re.Pattern]] = [(kw, _compile(kw)) for kw in cfg.keywords.get("exclude", [])]
        self.watch = set(cfg.watch.directives)

    def match(self, doc: Document) -> Match:
        text = searchable_text(doc)
        m = Match(doc=doc)
        m.keywords = sorted({kw for kw, pat in self.include.get(doc.language, []) if pat.search(text)})
        m.codes = code_matches(doc, self.cfg)
        m.watched = sorted(set(doc.transposes) & self.watch)
        if not m.codes and not m.watched and any(pat.search(text) for _, pat in self.exclude):
            m.keywords = []
        return m

    def run(self, docs: Iterable[Document]) -> List[Match]:
        return [m for m in (self.match(d) for d in docs) if m.passed]


def priority(m: Match) -> tuple:
    """Sort key for the cost cap: watched first, then code matches, keyword hits, document type."""
    rank = TYPE_RANK.get(_norm(m.doc.doc_type), 2)
    return (-len(m.watched), -min(len(m.codes), 1), -len(m.keywords), rank, m.doc.published.toordinal() * -1)


def cap(matches: List[Match], limit: int) -> Tuple[List[Match], List[Match]]:
    """Take the best match of each market in turn (EU, FR, ES, then again), so the cap is shared.
    Without this, the source with the richest classification codes (Spain) takes every slot."""
    by_market: Dict[str, List[Match]] = {}
    for m in sorted(matches, key=priority):
        by_market.setdefault(m.doc.market, []).append(m)
    watched = [m for m in sorted(matches, key=priority) if m.watched]      # watched texts always go first
    order: List[Match] = list(watched)
    queues = [q for _, q in sorted(by_market.items())]
    while any(queues):
        for q in queues:
            while q and q[0] in order:
                q.pop(0)
            if q:
                order.append(q.pop(0))
    return order[:limit], order[limit:]


def summarise_classification(doc: Document) -> Dict[str, List[str]]:
    return {k: v[:15] for k, v in doc.classification.items() if k.endswith("_labels") or k in ("headings", "department")}
