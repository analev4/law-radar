"""Spain: Boletín Oficial del Estado via the BOE open data API.

List: https://www.boe.es/datosabiertos/api/boe/sumario/{YYYYMMDD} (JSON), one summary per day.
      Days without a BOE (Sundays) return 404 and are skipped.
Text: https://www.boe.es/diario_boe/xml.php?id={BOE-A-...}: metadata, subject codes (materias) and
      the full text, with articles marked <p class="articulo">.
Link: the HTML page on boe.es, for readers.
See SOURCES.md.

Section 2 (Autoridades y personal: appointments and staff of named people) is never read, whatever
the config says. Section 3 is read only under the epigraphs listed in the config (by default the
collective agreements), because the rest of it is grants, prizes and similar acts.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional

from ..http import PoliteClient
from ..models import Article, Document
from ..textnorm import clean
from .transpose import transposed_directives
from .xmltext import text_of

SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{day}"
ITEM_XML_URL = "https://www.boe.es/diario_boe/xml.php?id={id}"
ITEM_HTML_URL = "https://www.boe.es/diario_boe/txt.php?id={id}"
NEVER_SECTIONS = {"2", "2A", "2B"}

_ARTICLE_HEAD = re.compile(r"^Art[íi]culo\s+(\d+[a-z]?(?:\s*(?:bis|ter|quater))?|[úu]nico)\b", re.IGNORECASE)
_OTHER_HEAD = re.compile(r"^(Disposici[óo]n|Anexo|ANEXO|Pre[áa]mbulo)\b")


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def sumario_items(payload: dict) -> List[Dict[str, str]]:
    """Flatten a daily summary into items with their section, department and epigraph."""
    out: List[Dict[str, str]] = []
    for diario in _as_list(payload.get("data", {}).get("sumario", {}).get("diario")):
        for sec in _as_list(diario.get("seccion")):
            for dep in _as_list(sec.get("departamento")):
                blocks = [(ep.get("nombre", ""), ep.get("item")) for ep in _as_list(dep.get("epigrafe"))]
                if isinstance(dep.get("texto"), dict):
                    blocks.append(("", dep["texto"].get("item")))
                if dep.get("item"):
                    blocks.append(("", dep.get("item")))
                for epigrafe, items in blocks:
                    for it in _as_list(items):
                        out.append({"id": it["identificador"], "title": it.get("titulo", ""),
                                    "section": sec.get("codigo", ""), "section_name": sec.get("nombre", ""),
                                    "department": dep.get("nombre", ""), "epigrafe": epigrafe or ""})
    return out


def wanted(item: Dict[str, str], sections: Iterable[str], section3_epigraphs: Iterable[str]) -> bool:
    sec = item["section"]
    if sec in NEVER_SECTIONS:
        return False
    if sec == "3":
        return item["epigrafe"].lower() in {e.lower() for e in section3_epigraphs}
    return sec in set(sections)


def _meta(root: ET.Element, tag: str) -> str:
    el = root.find(f"metadatos/{tag}")
    return clean("".join(el.itertext())) if el is not None else ""


def _date(s: str) -> Optional[dt.date]:
    return dt.datetime.strptime(s, "%Y%m%d").date() if s and len(s) == 8 and s.isdigit() else None


def parse_item_xml(raw: bytes, item: Optional[Dict[str, str]] = None) -> Document:
    root = ET.fromstring(raw)
    boe_id = _meta(root, "identificador")
    title = _meta(root, "titulo")
    materias = root.findall("analisis/materias/materia")

    articles: List[Article] = []
    paragraphs: List[str] = []
    current: Optional[List[str]] = None
    current_num = ""
    texto = root.find("texto")
    for p in (texto if texto is not None else []):
        line = text_of(p)
        if not line:
            continue
        paragraphs.append(line)
        head = _ARTICLE_HEAD.match(line) if "articulo" in (p.get("class") or "") else None
        if head or (_OTHER_HEAD.match(line) and "articulo" in (p.get("class") or "")):
            if current is not None:
                articles.append(Article(num=current_num, text="\n".join(current)))
            current, current_num = None, ""
            if head:
                num = head.group(1).lower().replace(" ", "")
                current_num = "unique" if num in ("único", "unico") else num
                current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        articles.append(Article(num=current_num, text="\n".join(current)))

    text = "\n".join([title] + paragraphs)
    headings = [h for h in ((item or {}).get("section_name", ""), (item or {}).get("epigrafe", "")) if h]
    return Document(
        id=f"es:{boe_id}", source="es", market="ES", native_id=boe_id, title=title, language="es",
        doc_type=_meta(root, "rango") or "Disposición",
        published=_date(_meta(root, "fecha_publicacion")),
        entry_into_force=_date(_meta(root, "fecha_vigencia")),
        url=ITEM_HTML_URL.format(id=boe_id), text_url=ITEM_XML_URL.format(id=boe_id),
        classification={
            "materias": [m.get("codigo", "") for m in materias],
            "materias_labels": [clean("".join(m.itertext())) for m in materias],
            "department": [_meta(root, "departamento")],
            "headings": headings,
            "section": [_meta(root, "seccion")],
        },
        transposes=transposed_directives(text), articles=articles, text=text,
    )


class ESBoeSource:
    id = "es"
    market = "ES"

    def __init__(self, client: PoliteClient, sections: List[str], section3_epigraphs: List[str]):
        self.client = client
        self.sections = sections
        self.section3_epigraphs = section3_epigraphs

    def fetch_since(self, since: dt.date, until: Optional[dt.date] = None) -> List[Document]:
        until = until or dt.date.today()
        docs: List[Document] = []
        day = since
        while day <= until:
            resp = self.client.get(SUMARIO_URL.format(day=day.strftime("%Y%m%d")),
                                   headers={"Accept": "application/json"})
            if resp.status_code == 404:          # no BOE that day
                day += dt.timedelta(days=1)
                continue
            resp.raise_for_status()
            for item in sumario_items(resp.json()):
                if not wanted(item, self.sections, self.section3_epigraphs):
                    continue
                xml = self.client.get(ITEM_XML_URL.format(id=item["id"]))
                xml.raise_for_status()
                docs.append(parse_item_xml(xml.content, item))
            day += dt.timedelta(days=1)
        return docs

    def fetch_text(self, doc: Document) -> Document:
        if doc.text:
            return doc
        resp = self.client.get(doc.text_url)
        resp.raise_for_status()
        fresh = parse_item_xml(resp.content)
        return fresh.model_copy(update={"classification": doc.classification or fresh.classification})
