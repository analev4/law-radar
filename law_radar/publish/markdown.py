"""Render a Digest as Markdown: digests/YYYY-WW.md and the body of the weekly Issue."""
from __future__ import annotations

import datetime as dt
from typing import List

from ..models import NOT_GENERATED, Digest, Entry, NoAiEntry

SCORE_LABELS = [
    ("forcing_mechanism", "Forcing mechanism"),
    ("findable", "Findable"),
    ("early", "Early"),
    ("gap_evidence", "Gap evidence"),
    ("crowding", "Crowding"),
]


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {d.strftime('%B')} {d.year}"


def week_number(digest: Digest) -> str:
    return digest.week.split("-W")[1]


def title(digest: Digest) -> str:
    return f"Law radar: week {week_number(digest)}"


def _short(text: str, n: int = 160) -> str:
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _entry(e: Entry) -> List[str]:
    out = [f"### {e.headline.text if e.headline.text != NOT_GENERATED else _short(e.title_original, 120)}", ""]
    out.append(f"**{e.market}** · {e.doc_type} · [{_short(e.title_original, 140)}]({e.url}) · "
               f"published {fmt_date(e.published)} · confidence: {e.confidence.level}")
    out.append("")
    out.append("**What changed:** " + " ".join(s.text for s in e.what_changed))
    out.append("")
    out.append(f"**Who:** {e.who.text}")
    out.append("")
    when = []
    if e.when.entry_into_force:
        when.append(f"in force {fmt_date(e.when.entry_into_force)}")
    facts = {f.id: f for f in e.facts}
    for d in e.when.deadlines:
        art = facts[d.fact_ref].citation.article if d.fact_ref in facts else ""
        when.append(f"{d.label.lower()} {fmt_date(d.date)}" + (f" ({art})" if art else ""))
    out.append("**When:** " + ("; ".join(when) if when else "the text sets no date beyond publication"))
    out.append("")
    out.append(f"**Penalty / money at stake:** {e.money.text}")
    out.append("")
    if e.scorecard:
        sc = e.scorecard
        sink = " (no forcing mechanism: sorted last)" if sc.sinks else ""
        out.append(f"**Scorecard ({sc.points}/{sc.max_points}){sink}:**")
        for key, label in SCORE_LABELS:
            line = getattr(sc, key)
            out.append(f"- {label}: **{line.verdict}**. {line.evidence}")
        out.append("")
    if e.list_recipes:
        out.append("**List recipes (hypotheses to test):**")
        for i, r in enumerate(e.list_recipes, 1):
            ds = f"[{r.dataset_name}]({r.dataset_url})" if r.dataset_url else r.dataset_name
            flag = "" if r.dataset_verified else " (unverified dataset)"
            strength = f" *{r.signal_strength} signal*" + (f": {r.caveat}" if r.caveat else "")
            out.append(f"{i}. {ds}{flag}. Filter: {r.filter}. Gap: {r.gap_evidence}. "
                       f"Number: {r.metric}.{strength}")
        out.append("")
    out.append("**Sources:**")
    for f in e.facts:
        out.append(f"- [{f.citation.article}]({f.citation.url}): \"{f.citation.quote}\"")
    out.append("")
    out.append(f"**Confidence:** {e.confidence.level}. {e.confidence.reason}")
    if e.not_generated:
        out.append("")
        out.append(f"*Not generated (failed the checks twice): {', '.join(e.not_generated)}.*")
    return out


def _no_ai(entries: List[NoAiEntry]) -> List[str]:
    out = ["| Market | Published | Title | Matched |", "|---|---|---|---|"]
    for e in entries:
        matched = ", ".join([k.rstrip("*") for k in e.matched_keywords] + e.matched_codes)
        out.append(f"| {e.market} | {e.published.isoformat()} | [{_short(e.title_original, 120)}]({e.url}) | {matched} |")
    return out


def render(digest: Digest) -> str:
    if digest.nothing_relevant:
        return (f"Law radar, week {week_number(digest)}: nothing relevant this week.\n\n"
                f"*{digest.disclaimer}*\n")

    w = digest.window
    n = len(digest.entries)
    lines = [f"# {title(digest)}", "",
             f"{fmt_date(w.since)} to {fmt_date(w.until)} · ICP: {digest.icp.name} · "
             f"{n} {'law' if n == 1 else 'laws'} flagged" + (" · keyword mode, no summaries" if digest.mode == "no-ai" else ""),
             "", f"*{digest.disclaimer}*", ""]
    if digest.mode == "no-ai":
        lines += _no_ai([e for e in digest.entries if isinstance(e, NoAiEntry)]) + [""]
    else:
        for e in digest.entries:
            if isinstance(e, Entry):
                lines += ["---", ""] + _entry(e) + [""]
        unread = [e for e in digest.entries if isinstance(e, NoAiEntry)]
        if unread:                                        # matches found after the AI digest was written
            lines += ["---", "", "### Keyword matches not read yet", ""] + _no_ai(unread) + [""]
    c = digest.run.counts
    source = {
        "claude-code": "AI fields written in Claude Code (/digest), no API cost.",
        "api": f"AI fields written with the Claude API, estimated spend ${digest.run.cost.estimated_usd:.2f}.",
        "replay": "AI fields replayed from saved answers.",
    }.get(digest.generated_by, "")
    lines += ["---", "",
              f"Run: {c.fetched} texts fetched, {c.new} new, keyword matches: {c.keyword_pass}"
              + (f", deferred by the weekly cap: {c.deferred_by_cap}" if c.deferred_by_cap else "")
              + (f", passed the relevance filter: {c.model_pass}, facts dropped by the citation check: {c.facts_dropped}"
                 if digest.mode == "ai" else "") + "." + (f" {source}" if source else ""),
              "", digest.attribution, ""]
    return "\n".join(lines)
