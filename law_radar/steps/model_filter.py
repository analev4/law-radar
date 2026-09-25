"""Small-model filter: could this text plausibly affect a company matching the ICP? Yes or no."""
from __future__ import annotations

import json

from ..config import Config
from ..llm import LLM
from ..models import Document, FilterOutput
from .context import system_prompt
from .keyword_filter import summarise_classification

EXCERPT_CHARS = 2000


def filter_message(doc: Document) -> str:
    return (
        f"Market: {doc.market}\nType: {doc.doc_type}\nPublished: {doc.published.isoformat()}\n"
        f"Title: {doc.title}\n"
        f"Classification: {json.dumps(summarise_classification(doc), ensure_ascii=False)}\n\n"
        f"Opening of the text:\n<excerpt>\n{doc.text[:EXCERPT_CHARS]}\n</excerpt>"
    )


def model_filter(llm: LLM, cfg: Config, doc: Document) -> FilterOutput:
    return llm.structured(
        step="filter", key=doc.id, model=cfg.models.filter,
        system=system_prompt("filter", cfg), user=filter_message(doc),
        output=FilterOutput, max_tokens=512,
    )
