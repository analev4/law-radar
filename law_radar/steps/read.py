"""Careful read: the stronger model extracts cited facts from the full text."""
from __future__ import annotations

from ..config import Config
from ..llm import LLM
from ..models import Document, ReadOutput
from .context import system_prompt


class TooLong(Exception):
    pass


def text_for_model(doc: Document, max_chars: int) -> str:
    """The full text, or the articles alone when the full text is over the limit. Never cut mid-text."""
    if len(doc.text) <= max_chars:
        return doc.text
    if doc.articles:
        articles_only = "\n".join(a.text for a in doc.articles)
        if len(articles_only) <= max_chars:
            return articles_only
    raise TooLong(f"{doc.id}: {len(doc.text):,} characters, over the {max_chars:,} limit")


def read_message(doc: Document, text: str) -> str:
    return (
        f"Market: {doc.market}\nType: {doc.doc_type}\nPublished: {doc.published.isoformat()}\n"
        f"Entry into force (from source metadata): "
        f"{doc.entry_into_force.isoformat() if doc.entry_into_force else 'not given'}\n"
        f"Title: {doc.title}\nLanguage: {doc.language}\n\n"
        f"<document>\n{text}\n</document>"
    )


def read(llm: LLM, cfg: Config, doc: Document) -> ReadOutput:
    text = text_for_model(doc, cfg.limits.max_text_chars)
    return llm.structured(
        step="read", key=doc.id, model=cfg.models.read,
        system=system_prompt("read", cfg), user=read_message(doc, text),
        output=ReadOutput, max_tokens=16000, effort=cfg.models.read_effort,
    )
