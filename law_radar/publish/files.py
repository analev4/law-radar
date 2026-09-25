"""Write digests/YYYY-WW.md, digests/YYYY-WW.json and digests/YYYY-WW.matches.json.

A second run in the same ISO week merges into the week's files instead of replacing them, so a
run that finds nothing new never wipes what an earlier run found.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from ..models import Counts, Digest, Document, Entry, Window
from .markdown import render

SUMMED_COUNTS = ("fetched", "new", "keyword_pass", "deferred_by_cap", "model_pass", "read", "facts_dropped",
                 "fields_not_generated")


def stem(digest: Digest) -> str:
    year, week = digest.week.split("-W")
    return f"{year}-{week}"


def _entry_order(e) -> tuple:
    from ..pipeline import _sort_key                      # local import: pipeline imports publish
    if isinstance(e, Entry):
        return (0,) + _sort_key(e)
    return (1, -e.published.toordinal(), e.id)


def merge(old: Digest, new: Digest) -> Digest:
    """The week's digest after a second run. The newer version of an entry wins, except that a read
    entry is never replaced by a bare keyword match."""
    by_id: Dict[str, object] = {e.id: e for e in old.entries}
    for e in new.entries:
        if isinstance(by_id.get(e.id), Entry) and not isinstance(e, Entry):
            continue
        by_id[e.id] = e
    entries = sorted(by_id.values(), key=_entry_order)
    counts = Counts(**{k: getattr(old.run.counts, k) + getattr(new.run.counts, k) for k in SUMMED_COUNTS},
                    published=len(entries))
    run = new.run.model_copy(update={"counts": counts, "sources": old.run.sources + new.run.sources})
    mode = "ai" if "ai" in (old.mode, new.mode) else "no-ai"
    generated_by = new.generated_by if new.mode == "ai" else old.generated_by
    return new.model_copy(update={
        "entries": entries, "run": run, "mode": mode, "generated_by": generated_by,
        "nothing_relevant": not entries,
        "window": Window(since=min(old.window.since, new.window.since), until=max(old.window.until, new.window.until)),
    })


def write(digest: Digest, out_dir: Path, replace: bool = False) -> Tuple[Path, Path]:
    """Write the week's digest. Merges with an existing file for that week unless replace=True
    (used by /digest, which rebuilds the week from its full list of matches)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{stem(digest)}.md"
    js = out_dir / f"{stem(digest)}.json"
    if js.exists() and not replace:
        digest = merge(Digest.model_validate_json(js.read_text(encoding="utf-8")), digest)
    md.write_text(render(digest), encoding="utf-8")
    js.write_text(digest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return md, js


def write_matches(digest: Digest, docs: List[Document], out_dir: Path) -> Path:
    """The week's keyword matches with full metadata (no text), for /digest in Claude Code.
    Merged with the week's earlier matches, if any."""
    path = out_dir / f"{stem(digest)}.matches.json"
    window = {"since": digest.window.since.isoformat(), "until": digest.window.until.isoformat()}
    counts = digest.run.counts.model_dump(include={"fetched", "new", "keyword_pass"})
    documents = [d.model_dump(mode="json", exclude={"text", "articles"}) for d in docs]
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        known = {d["id"] for d in documents}
        documents = [d for d in old.get("documents", []) if d["id"] not in known] + documents
        window = {"since": min(old["window"]["since"], window["since"]), "until": max(old["window"]["until"], window["until"])}
        counts = {k: old.get("counts", {}).get(k, 0) + v for k, v in counts.items()}
    payload = {"week": digest.week, "window": window, "counts": counts, "documents": documents}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
