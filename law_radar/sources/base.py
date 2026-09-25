"""The interface every source adapter implements.

An adapter turns one official journal into Document objects. It knows nothing about the ICP,
the model or the digest. See CONTRIBUTING.md, "Writing a source adapter".
"""
from __future__ import annotations

import datetime as dt
from typing import List, Protocol

from ..models import Document


class Source(Protocol):
    id: str        # short id used in Document.id prefixes and the config: "eu", "fr", "es"
    market: str    # "EU", "FR", "ES"

    def fetch_since(self, since: dt.date, until: dt.date) -> List[Document]:
        """Every document published in [since, until], with metadata. Text may be left empty."""
        ...

    def fetch_text(self, doc: Document) -> Document:
        """Return the document with .text (and .articles when the source marks them) filled in."""
        ...
