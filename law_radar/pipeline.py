"""fetch -> dedupe -> filter -> read -> score -> publish"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Callable, Dict, List, Optional, Sequence

from .config import Config, Dataset
from .http import Blocked, FetchError
from .llm import LLM, LLMError, MissingRecording
from .models import Digest, Document, Entry, IcpRef, NoAiEntry, RunInfo, SourceReport, Window
from .sources.base import Source
from .state import State
from .steps.assemble import Assembler, Stats
from .steps.keyword_filter import KeywordFilter, cap
from .steps.model_filter import model_filter
from .steps.read import TooLong, read
from .steps.score import score

Log = Callable[[str], None]


def iso_week(day: dt.date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _sort_key(e) -> tuple:
    if isinstance(e, Entry):
        sc = e.scorecard
        nd = e.when.next_deadline
        return (bool(sc and sc.sinks), nd is None, nd or dt.date.max, -(sc.points if sc else 0), e.id)
    return (False, False, dt.date.max, 0, e.id)


def run_pipeline(cfg: Config, sources: Sequence[Source], state: State, *, today: dt.date,
                 since: dt.date, until: dt.date, datasets: Dict[str, Dataset],
                 llm: Optional[LLM] = None, no_ai: bool = False, log: Log = print,
                 max_documents: Optional[int] = None, waiting: Optional[List[str]] = None,
                 matches_out: Optional[List[Document]] = None) -> Digest:
    """Run one week. In exchange mode, documents whose answers aren't written yet are added to
    `waiting` and left out of the digest; run again once the answers exist."""
    run = RunInfo()
    counts = run.counts
    for celex in cfg.watch.directives:
        state.watchlist.setdefault(celex, {"transposed_by": []})

    # 1. fetch
    fetched = []
    by_source = {s.id: s for s in sources}
    for src in sources:
        report = SourceReport(id=src.id)
        try:
            docs = src.fetch_since(since, until)
        except (Blocked, FetchError, OSError, ValueError) as exc:
            report.errors.append(str(exc))
            log(f"[{src.id}] fetch failed: {exc}")
            docs = []
        report.fetched = len(docs)
        run.sources.append(report)
        fetched.extend(docs)
    carried = [d for d in state.deferred if d.source in by_source]
    state.deferred = [d for d in state.deferred if d.source not in by_source]
    counts.fetched = len(fetched)

    # 2. dedupe
    new, seen_now = [], set()
    for d in fetched + carried:
        if state.is_seen(d.id) or d.id in seen_now:
            continue
        seen_now.add(d.id)
        new.append(d)
    counts.new = len(new)
    for report in run.sources:
        report.new = sum(1 for d in new if d.source == report.id)

    # 3a. keyword filter (plain code)
    matches = KeywordFilter(cfg).run(new)
    counts.keyword_pass = len(matches)
    matched_ids = {m.doc.id for m in matches}
    for d in new:
        if d.id not in matched_ids:
            state.mark_seen(d.id, today)

    if matches_out is not None:
        matches_out.extend(m.doc for m in matches)

    entries: List = []
    if no_ai:
        for m in sorted(matches, key=lambda m: (m.doc.published, m.doc.id), reverse=True):
            entries.append(NoAiEntry(id=m.doc.id, market=m.doc.market, doc_type=m.doc.doc_type,
                                     title_original=m.doc.title, published=m.doc.published, url=m.doc.url,
                                     matched_keywords=m.keywords, matched_codes=m.codes + m.watched))
            state.mark_seen(m.doc.id, today)
        counts.published = len(entries)
        return _digest(cfg, today, since, until, entries, run, "no-ai", "no-ai")

    assert llm is not None, "AI mode needs an LLM"
    # Cost cap: applied before any model call. Documents over the cap wait for the next run.
    kept, over = cap(matches, max_documents if max_documents is not None else cfg.limits.max_documents_per_run)
    counts.deferred_by_cap = len(over)
    state.deferred.extend(m.doc for m in over)

    assembler = Assembler(llm, cfg, datasets, today)
    stats = Stats()
    for m in kept:
        doc = m.doc
        src = by_source[doc.source]
        try:
            if not doc.text:
                doc = src.fetch_text(doc)
        except (Blocked, FetchError, OSError) as exc:
            _report(run, doc.source).errors.append(f"{doc.id}: {exc}")
            state.deferred.append(m.doc)
            log(f"[{doc.id}] text fetch failed, deferred: {exc}")
            continue
        try:
            verdict = model_filter(llm, cfg, doc)
            if not verdict.relevant:
                log(f"[{doc.id}] filter: no. {verdict.reason}")
                state.mark_seen(doc.id, today)
                continue
            counts.model_pass += 1
            log(f"[{doc.id}] filter: yes. {verdict.reason}")
            extraction = read(llm, cfg, doc)
            counts.read += 1
            # Score only on facts that survived validation.
            facts = assembler.facts(doc, extraction.facts, stats)
            score_out = score(llm, cfg, datasets, doc, list(facts.values()), today) if facts else None
            entry = assembler.build(doc, extraction, facts, score_out, stats)
        except MissingRecording as exc:
            stats.drop_reasons.clear()
            if waiting is not None:
                waiting.append(doc.id)
            log(f"[{doc.id}] waiting for answers: {exc}")
            continue
        except TooLong as exc:
            _report(run, doc.source).errors.append(str(exc))
            state.mark_seen(doc.id, today)
            log(f"[{doc.id}] skipped: {exc}")
            continue
        except LLMError as exc:
            _report(run, doc.source).errors.append(f"{doc.id}: {exc}")
            state.deferred.append(m.doc)
            log(f"[{doc.id}] model call failed, deferred: {exc}")
            continue
        state.mark_seen(doc.id, today)
        for fid, reason in stats.drop_reasons:
            log(f"[{doc.id}] dropped {fid}: {reason}")
        stats.drop_reasons.clear()
        if entry is None:
            log(f"[{doc.id}] no fact survived the citation checks; nothing published")
            continue
        for celex in entry.transposes:
            if celex in state.watchlist and entry.id not in state.watchlist[celex]["transposed_by"]:
                state.watchlist[celex]["transposed_by"].append(entry.id)
        entries.append(entry)

    counts.facts_dropped = stats.facts_dropped
    counts.fields_not_generated = stats.fields_not_generated
    entries.sort(key=_sort_key)
    counts.published = len(entries)
    run.cost = llm.tracker.to_model()
    return _digest(cfg, today, since, until, entries, run, "ai", llm.generator)


def _report(run: RunInfo, source_id: str) -> SourceReport:
    for r in run.sources:
        if r.id == source_id:
            return r
    r = SourceReport(id=source_id)
    run.sources.append(r)
    return r


def _digest(cfg: Config, today: dt.date, since: dt.date, until: dt.date, entries: List,
            run: RunInfo, mode: str, generated_by: str) -> Digest:
    return Digest(
        week=iso_week(until), window=Window(since=since, until=until), mode=mode, generated_by=generated_by,
        icp=IcpRef(name=cfg.icp.name, config_sha256=cfg.sha256 or hashlib.sha256(b"").hexdigest()),
        nothing_relevant=not entries, entries=entries, run=run,
    )
