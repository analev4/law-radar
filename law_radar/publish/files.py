"""Write digests/YYYY-WW.md and digests/YYYY-WW.json."""
from __future__ import annotations

from pathlib import Path
import json
from typing import List, Tuple

from ..models import Digest, Document
from .markdown import render


def stem(digest: Digest) -> str:
    year, week = digest.week.split("-W")
    return f"{year}-{week}"


def write(digest: Digest, out_dir: Path) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{stem(digest)}.md"
    js = out_dir / f"{stem(digest)}.json"
    md.write_text(render(digest), encoding="utf-8")
    js.write_text(digest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return md, js


def write_matches(digest: Digest, docs: List[Document], out_dir: Path) -> Path:
    """The week's keyword matches with full metadata (no text), for /digest in Claude Code."""
    path = out_dir / f"{stem(digest)}.matches.json"
    payload = {
        "week": digest.week,
        "window": {"since": digest.window.since.isoformat(), "until": digest.window.until.isoformat()},
        "counts": digest.run.counts.model_dump(include={"fetched", "new", "keyword_pass"}),
        "documents": [d.model_dump(mode="json", exclude={"text", "articles"}) for d in docs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
