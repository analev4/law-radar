"""Golden fixtures: real public texts saved as the sources return them.

Used by the tests (replaying recorded model responses) and by `law-radar record-fixtures`
(calling the API once and saving those responses). Both go through the same code path, so the
recording keys always match.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from .config import FRSource
from .models import Document
from .sources import eu_cellar, fr_dila

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN_TODAY = dt.date(2026, 9, 28)        # the Monday the golden run pretends to be

EU_RELEVANT = "32023L0970"                  # Pay Transparency Directive
EU_IRRELEVANT = "32026R1933"                # fishing opportunities, Seychelles protocol
EU_GOLDEN = [EU_RELEVANT, EU_IRRELEVANT]

# A subset of the real DILA dump JORF_20260307-002619.tar.gz (files for three texts plus the issue's
# table of contents), so the test exercises the real parser on real bytes.
FR_ARCHIVE = "JORF_20260307-002619.subset.tar.gz"
FR_RELEVANT = "JORFTEXT000053634597"        # Décret n° 2026-168, apprentice hiring aid
FR_EXCLUDED = "JORFTEXT000053635455"        # naturalisation decree: excluded heading, never read
FR_IRRELEVANT = "JORFTEXT000053634692"      # label rouge specification: no keyword match
FR_DAY = dt.date(2026, 3, 7)


def load_eu(celex: str, with_text: bool = True) -> Document:
    payload = json.loads((FIXTURES / "eu" / f"{celex}.sparql.json").read_text(encoding="utf-8"))
    pairs = eu_cellar.parse_list(eu_cellar._bindings(payload["list"]), include_corrigenda=False)
    by_work = {w: d for w, d in pairs}
    eu_cellar.apply_meta(by_work, eu_cellar._bindings(payload["meta"]))
    doc = pairs[0][1]
    if with_text:
        raw = (FIXTURES / "eu" / f"{celex}.xhtml").read_text(encoding="utf-8")
        text, articles = eu_cellar.parse_xhtml(raw)
        doc = doc.model_copy(update={"text": text, "articles": articles})
    return doc


class FixtureSource:
    """A Source that serves saved documents instead of calling the publisher."""

    def __init__(self, source_id: str, market: str, docs: List[Document]):
        self.id = source_id
        self.market = market
        self._docs: Dict[str, Document] = {d.id: d for d in docs}

    def fetch_since(self, since: dt.date, until: Optional[dt.date] = None) -> List[Document]:
        return [d.model_copy(update={"text": "", "articles": []}) for d in self._docs.values()]

    def fetch_text(self, doc: Document) -> Document:
        return self._docs[doc.id]


def eu_fixture_source() -> FixtureSource:
    return FixtureSource("eu", "EU", [load_eu(c) for c in EU_GOLDEN])


def load_fr() -> List[Document]:
    cfg = FRSource()
    data = (FIXTURES / "fr" / FR_ARCHIVE).read_bytes()
    return fr_dila.parse_archive(data, fr_dila.LIST_URL + "JORF_20260307-002619.tar.gz", FR_DAY, FR_DAY,
                                 cfg.natures, cfg.exclude_headings)


def fr_fixture_source() -> FixtureSource:
    return FixtureSource("fr", "FR", load_fr())


def golden_sources() -> List[FixtureSource]:
    return [eu_fixture_source(), fr_fixture_source()]
