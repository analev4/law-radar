"""EU Official Journal, L series, via the Publications Office's Cellar.

List:  SPARQL on https://publications.europa.eu/webapi/rdf/sparql (no auth).
Text:  content negotiation on http://publications.europa.eu/resource/celex/{CELEX}.
Link:  EUR-Lex, for readers. EUR-Lex itself sits behind a bot challenge, so we never fetch it.
See SOURCES.md.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Tuple

from ..http import PoliteClient
from ..models import Article, Document
from ..textnorm import clean
from .xmltext import BLOCK as _BLOCK, local as _local, text_of as _text_of

SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
CELEX_URL = "http://publications.europa.eu/resource/celex/{celex}"
EURLEX_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
OJ_L = "http://publications.europa.eu/resource/authority/document-collection/OJ-L"
PAGE_SIZE = 500
BATCH = 40

DOC_TYPES = {
    "L": "Directive", "R": "Regulation", "D": "Decision", "H": "Recommendation",
    "O": "Guideline", "A": "Agreement", "G": "Resolution", "Q": "Rules of procedure",
}

PREFIXES = "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n" \
           "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n" \
           "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"


def list_query(since: dt.date, until: dt.date, offset: int) -> str:
    return PREFIXES + f"""
SELECT DISTINCT ?work ?celex ?pub ?type ?eif WHERE {{
  ?work cdm:official-journal-act_part_of_collection_document <{OJ_L}> ;
        cdm:official-journal-act_date_publication ?pub ;
        cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?work cdm:resource_legal_type ?type }}
  OPTIONAL {{ ?work cdm:resource_legal_date_entry-into-force ?eif }}
  FILTER(?pub >= "{since.isoformat()}"^^xsd:date && ?pub <= "{until.isoformat()}"^^xsd:date)
}} ORDER BY ?pub ?celex LIMIT {PAGE_SIZE} OFFSET {offset}"""


def meta_query(works: Iterable[str]) -> str:
    values = " ".join(f"<{w}>" for w in works)
    return PREFIXES + f"""
SELECT ?work ?title ?ev ?evl ?dir WHERE {{
  VALUES ?work {{ {values} }}
  {{ ?e cdm:expression_belongs_to_work ?work ;
        cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
        cdm:expression_title ?title . }}
  UNION {{ ?work cdm:work_is_about_concept_eurovoc ?ev .
           OPTIONAL {{ ?ev skos:prefLabel ?evl FILTER(LANG(?evl) = "en") }} }}
  UNION {{ ?work cdm:resource_legal_is_about_concept_directory-code ?dir }}
}}"""


def _bindings(payload: dict) -> List[Dict[str, str]]:
    return [{k: v["value"] for k, v in row.items()} for row in payload["results"]["bindings"]]


def parse_list(rows: List[Dict[str, str]], include_corrigenda: bool) -> List[Tuple[str, Document]]:
    out: List[Tuple[str, Document]] = []
    seen = set()
    for row in rows:
        celex = row["celex"]
        if celex in seen:
            continue
        seen.add(celex)
        if not include_corrigenda and re.search(r"R\(\d+\)$", celex):
            continue
        eif = row.get("eif")
        doc = Document(
            id=f"eu:{celex}", source="eu", market="EU", native_id=celex,
            title=celex, language="en",
            doc_type=DOC_TYPES.get(row.get("type", ""), row.get("type") or "Act"),
            published=dt.date.fromisoformat(row["pub"][:10]),
            entry_into_force=dt.date.fromisoformat(eif[:10]) if eif and not eif.startswith("9999") else None,
            url=EURLEX_URL.format(celex=celex),
            text_url=CELEX_URL.format(celex=celex),
        )
        out.append((row["work"], doc))
    return out


def apply_meta(docs_by_work: Dict[str, Document], rows: List[Dict[str, str]]) -> None:
    for row in rows:
        doc = docs_by_work.get(row["work"])
        if not doc:
            continue
        cls = doc.classification
        if row.get("title") and doc.title == doc.native_id:
            doc.title = clean(row["title"])
        if row.get("ev"):
            ev_id = row["ev"].rsplit("/", 1)[-1]
            if ev_id not in cls.setdefault("eurovoc", []):
                cls["eurovoc"].append(ev_id)
            if row.get("evl") and row["evl"] not in cls.setdefault("eurovoc_labels", []):
                cls["eurovoc_labels"].append(row["evl"])
        if row.get("dir"):
            code = row["dir"].rsplit("/", 1)[-1]
            if code not in cls.setdefault("directory", []):
                cls["directory"].append(code)


# ---------------------------------------------------------------------------
# XHTML to text
# ---------------------------------------------------------------------------

class _TagStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def parse_xhtml(raw: str) -> Tuple[str, List[Article]]:
    """Full text and articles from an OJ XHTML file. Articles are div.eli-subdivision with id art_N."""
    try:
        root = ET.fromstring(raw.encode("utf-8") if isinstance(raw, str) else raw)
    except ET.ParseError:
        stripper = _TagStripper()
        stripper.feed(raw)
        return clean("".join(stripper.parts)), []

    body = next((el for el in root.iter() if _local(el.tag) == "body"), root)
    text = _text_of(body)
    articles: List[Article] = []
    for el in body.iter():
        el_id = el.get("id") or ""
        m = re.fullmatch(r"art_(\w+)", el_id)
        if _local(el.tag) == "div" and m:
            heading = None
            for p in el.iter():
                if "oj-sti-art" in (p.get("class") or ""):
                    heading = clean("".join(p.itertext()))
                    break
            articles.append(Article(num=m.group(1).lower(), heading=heading, text=_text_of(el)))
    return text, articles


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class EUCellarSource:
    id = "eu"
    market = "EU"

    def __init__(self, client: PoliteClient, include_corrigenda: bool = False):
        self.client = client
        self.include_corrigenda = include_corrigenda

    def _sparql(self, query: str) -> dict:
        resp = self.client.get(SPARQL_URL, params={"query": query, "format": "application/sparql-results+json"})
        resp.raise_for_status()
        return resp.json()

    def fetch_since(self, since: dt.date, until: Optional[dt.date] = None) -> List[Document]:
        until = until or dt.date.today()
        pairs: List[Tuple[str, Document]] = []
        offset = 0
        while True:
            rows = _bindings(self._sparql(list_query(since, until, offset)))
            pairs.extend(parse_list(rows, self.include_corrigenda))
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        by_work = {w: d for w, d in pairs}
        works = list(by_work)
        for i in range(0, len(works), BATCH):
            apply_meta(by_work, _bindings(self._sparql(meta_query(works[i:i + BATCH]))))
        return [d for _, d in pairs]

    def fetch_text(self, doc: Document) -> Document:
        resp = self.client.get(doc.text_url, headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"})
        resp.raise_for_status()
        text, articles = parse_xhtml(resp.text)
        return doc.model_copy(update={"text": text, "articles": articles})
