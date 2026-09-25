"""Run state, committed by the workflow.

state/seen.json      IDs of documents already handled, with the date first seen. IDs only.
state/deferred.json  documents over the cost cap, kept for the next run (metadata, no text).
state/watchlist.json EU directives to follow into national law.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .models import Document

KEEP_SEEN_DAYS = 120


class State:
    def __init__(self, directory: Path):
        self.dir = directory
        self.seen: Dict[str, str] = {}
        self.last_until: Optional[dt.date] = None
        self.deferred: List[Document] = []
        self.watchlist: Dict[str, dict] = {}

    @classmethod
    def load(cls, directory: Path) -> "State":
        st = cls(directory)
        seen_path = directory / "seen.json"
        if seen_path.exists():
            data = json.loads(seen_path.read_text(encoding="utf-8"))
            st.seen = data.get("seen", {})
            if data.get("last_until"):
                st.last_until = dt.date.fromisoformat(data["last_until"])
        deferred_path = directory / "deferred.json"
        if deferred_path.exists():
            st.deferred = [Document.model_validate(d) for d in json.loads(deferred_path.read_text(encoding="utf-8"))]
        watch_path = directory / "watchlist.json"
        if watch_path.exists():
            st.watchlist = json.loads(watch_path.read_text(encoding="utf-8"))
        return st

    def is_seen(self, doc_id: str) -> bool:
        return doc_id in self.seen

    def mark_seen(self, doc_id: str, today: dt.date) -> None:
        self.seen.setdefault(doc_id, today.isoformat())

    def save(self, today: dt.date, until: dt.date) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        cutoff = (today - dt.timedelta(days=KEEP_SEEN_DAYS)).isoformat()
        self.seen = {k: v for k, v in sorted(self.seen.items()) if v >= cutoff}
        self.last_until = until
        (self.dir / "seen.json").write_text(
            json.dumps({"version": 1, "last_until": until.isoformat(), "seen": self.seen}, indent=0) + "\n",
            encoding="utf-8")
        (self.dir / "deferred.json").write_text(
            json.dumps([d.model_dump(mode="json", exclude={"text", "articles"}) for d in self.deferred],
                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (self.dir / "watchlist.json").write_text(
            json.dumps(self.watchlist, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
