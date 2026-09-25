"""France: Journal officiel ("Lois et décrets") via DILA's open data dumps.

List + text: https://echanges.dila.gouv.fr/OPENDATA/JORF/ publishes JORF_YYYYMMDD-HHMMSS.tar.gz,
usually twice a day. Each archive holds XML for the texts published or corrected since the last one.
Link:        Légifrance, for readers. Légifrance refuses automated requests, so we never fetch it.
See SOURCES.md.

The archives also carry corrections to old texts, so a text is kept only when its DATE_PUBLI is
inside the run window. Texts filed under excluded headings ("Mesures nominatives": appointments of
named people) are dropped before anything else sees them.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..http import PoliteClient
from ..models import Article, Document
from ..textnorm import clean
from .transpose import transposed_directives
from .xmltext import text_of

LIST_URL = "https://echanges.dila.gouv.fr/OPENDATA/JORF/"
LEGIFRANCE_URL = "https://www.legifrance.gouv.fr/jorf/id/{id}"
ARCHIVE_RE = re.compile(r"JORF_(\d{8})-(\d{6})\.tar\.gz")
CACHE = Path(__file__).resolve().parent.parent.parent / ".cache" / "dila"

DOC_TYPES = {"LOI": "Loi", "ORDONNANCE": "Ordonnance", "DECRET": "Décret", "ARRETE": "Arrêté",
             "DECISION": "Décision", "CIRCULAIRE": "Circulaire", "AVIS": "Avis", "DELIBERATION": "Délibération"}


def list_archives(html: str) -> List[Tuple[str, dt.date]]:
    names = sorted(set(ARCHIVE_RE.findall(html)))
    return [(f"JORF_{d}-{t}.tar.gz", dt.datetime.strptime(d, "%Y%m%d").date()) for d, t in names]


def archives_for_window(archives: Iterable[Tuple[str, dt.date]], since: dt.date, until: dt.date) -> List[str]:
    """A text published on day D arrives in the dump of D (evening) or D+1 (after midnight)."""
    lo, hi = since - dt.timedelta(days=1), until + dt.timedelta(days=1)
    return [name for name, day in archives if lo <= day <= hi]


def _xml(data: bytes) -> Optional[ET.Element]:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _find_text(root: ET.Element, path: str) -> str:
    el = root.find(path)
    return clean("".join(el.itertext())) if el is not None else ""


def _block(root: ET.Element, path: str) -> str:
    el = root.find(path)
    return text_of(el) if el is not None else ""


def _headings(container: ET.Element) -> Dict[str, List[str]]:
    """Map each text id to the table-of-contents headings above it."""
    out: Dict[str, List[str]] = {}

    def walk(node: ET.Element, path: List[str]) -> None:
        for child in node:
            if child.tag == "TM":
                title = _find_text(child, "TITRE_TM")
                walk(child, path + [title] if title else path)
            elif child.tag == "LIEN_TXT" and child.get("idtxt"):
                out[child.get("idtxt")] = path

    structure = container.find("STRUCTURE_TXT")
    if structure is not None:
        walk(structure, [])
    return out


def _article_order(struct_id: str, structs: Dict[str, ET.Element], sections: Dict[str, ET.Element]) -> List[str]:
    """Article ids in reading order, following LIEN_SECTION_TA into sections."""
    order: List[str] = []

    def walk(node: Optional[ET.Element]) -> None:
        if node is None:
            return
        for child in node:
            if child.tag == "LIEN_ART" and child.get("id"):
                order.append(child.get("id"))
            elif child.tag == "LIEN_SECTION_TA" and child.get("id"):
                sec = sections.get(child.get("id"))
                walk(sec.find("STRUCTURE_TA") if sec is not None else None)

    root = structs.get(struct_id)
    walk(root.find("STRUCT") if root is not None else None)
    return order


def parse_archive(data: bytes, archive_url: str, since: dt.date, until: dt.date, natures: List[str],
                  exclude_headings: List[str], only: Optional[str] = None) -> List[Document]:
    versions: Dict[str, ET.Element] = {}
    structs: Dict[str, ET.Element] = {}
    sections: Dict[str, ET.Element] = {}
    articles: Dict[str, Tuple[str, str, str]] = {}      # id -> (parent text id, num, text)
    headings: Dict[str, List[str]] = {}

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(".xml"):
                continue
            name = member.name
            kind = ("version" if "/texte/version/" in name else "struct" if "/texte/struct/" in name
                    else "section" if "/section_ta/" in name else "article" if "/article/" in name
                    else "container" if "/conteneur/" in name else None)
            if kind is None:
                continue
            root = _xml(tar.extractfile(member).read())
            if root is None:
                continue
            if kind == "container":
                headings.update(_headings(root))
                continue
            node_id = _find_text(root, ".//ID")
            if kind == "version":
                versions[node_id] = root
            elif kind == "struct":
                structs[node_id] = root
            elif kind == "section":
                sections[node_id] = root
            else:
                parent = root.find(".//CONTEXTE/TEXTE")
                contenu = root.find(".//BLOC_TEXTUEL/CONTENU")   # an empty NOTA <CONTENU/> can come first
                articles[node_id] = (parent.get("cid") if parent is not None else "",
                                     _find_text(root, ".//META_ARTICLE/NUM"),
                                     text_of(contenu) if contenu is not None else "")

    wanted = {n.upper() for n in natures}
    excluded = [h.lower() for h in exclude_headings]
    docs: List[Document] = []
    for text_id, root in versions.items():
        if only and text_id != only:
            continue
        nature = _find_text(root, ".//META_COMMUN/NATURE").upper()
        published = _find_text(root, ".//DATE_PUBLI")
        if nature not in wanted or not published:
            continue
        pub = dt.date.fromisoformat(published)
        if not (since <= pub <= until):
            continue
        path = headings.get(text_id, [])
        if any(any(x in h.lower() for x in excluded) for h in path):
            continue

        order = _article_order(text_id, structs, sections)
        if not order:                                    # fall back to every article of this text
            order = [a for a, (parent, _, _) in articles.items() if parent == text_id]
        arts: List[Article] = []
        for art_id in order:
            if art_id in articles:
                _, num, body = articles[art_id]
                num = (num or str(len(arts) + 1)).strip()
                arts.append(Article(num=num.lower(), text=f"Article {num}\n{body}"))

        title = _find_text(root, ".//TITREFULL") or _find_text(root, ".//TITRE")
        notice = _block(root, ".//NOTICE")
        visas = _block(root, ".//VISAS")
        text = "\n".join(p for p in [title, notice, visas] + [a.text for a in arts] if p)
        ministry = _find_text(root, ".//MINISTERE")
        docs.append(Document(
            id=f"fr:{text_id}", source="fr", market="FR", native_id=text_id,
            title=title, language="fr", doc_type=DOC_TYPES.get(nature, nature.title()),
            published=pub, url=LEGIFRANCE_URL.format(id=text_id), text_url=f"{archive_url}#{text_id}",
            classification={"headings": [h for h in path if h], "department": [ministry] if ministry else [],
                            "nor": [_find_text(root, ".//NOR")]},
            transposes=transposed_directives(text), articles=arts, text=text,
        ))
    return docs


class FRDilaSource:
    id = "fr"
    market = "FR"

    def __init__(self, client: PoliteClient, natures: List[str], exclude_headings: List[str],
                 cache: Path = CACHE):
        self.client = client
        self.natures = natures
        self.exclude_headings = exclude_headings
        self.cache = cache

    def _download(self, name: str) -> bytes:
        path = self.cache / name
        if path.exists():
            return path.read_bytes()
        resp = self.client.get(LIST_URL + name)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return resp.content

    def fetch_since(self, since: dt.date, until: Optional[dt.date] = None) -> List[Document]:
        until = until or dt.date.today()
        listing = self.client.get(LIST_URL)
        listing.raise_for_status()
        docs: Dict[str, Document] = {}
        for name in archives_for_window(list_archives(listing.text), since, until):
            for doc in parse_archive(self._download(name), LIST_URL + name, since, until,
                                     self.natures, self.exclude_headings):
                docs[doc.id] = doc                     # a later archive replaces an earlier version
        return list(docs.values())

    def fetch_text(self, doc: Document) -> Document:
        if doc.text:
            return doc
        archive_url, _, text_id = doc.text_url.partition("#")
        name = archive_url.rsplit("/", 1)[-1]
        found = parse_archive(self._download(name), archive_url, doc.published, doc.published,
                              self.natures, [], only=text_id)
        if not found:
            raise ValueError(f"{doc.id} not found in {name}")
        return found[0]
