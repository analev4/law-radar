"""Viability scorecard and list recipes. The model gives verdicts; points are computed here."""
from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List

from ..config import Config, Dataset
from ..llm import LLM
from ..models import Document, Fact, ScoreOutput
from .context import datasets_text, system_prompt

VALUE = {"yes": 2, "unclear": 1, "no": 0}
CROWDING_VALUE = {"yes": 0, "unclear": 1, "no": 2}      # crowded is bad
MAX_POINTS = 2 + 2 + 2 + 4 + 2                          # gap evidence counts double


def points(forcing: str, findable: str, early: str, gap: str, crowding: str) -> int:
    return VALUE[forcing] + VALUE[findable] + VALUE[early] + 2 * VALUE[gap] + CROWDING_VALUE[crowding]


def score_message(doc: Document, facts: List[Fact], today: dt.date) -> str:
    rows = [{"id": f.id, "kind": f.kind, "statement": f.statement, "article": f.citation.article,
             "quote": f.citation.quote, "date": f.date.isoformat() if f.date else None} for f in facts]
    return (
        f"Today: {today.isoformat()}\nMarket: {doc.market}\nType: {doc.doc_type}\nTitle: {doc.title}\n\n"
        f"Validated facts:\n{json.dumps(rows, ensure_ascii=False, indent=1)}"
    )


def score(llm: LLM, cfg: Config, datasets: Dict[str, Dataset], doc: Document,
          facts: List[Fact], today: dt.date) -> ScoreOutput:
    return llm.structured(
        step="score", key=doc.id, model=cfg.models.read,
        system=system_prompt("score", cfg, datasets_text(datasets, cfg.icp.markets)),
        user=score_message(doc, facts, today),
        output=ScoreOutput, max_tokens=8000, effort=cfg.models.read_effort,
    )
