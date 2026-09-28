"""Spain: grants awarded (concesiones) from the BDNS / SNPSAP public API, companies only.

API:      https://www.infosubvenciones.es/bdnstrans/api/concesiones/busqueda (no key)
Licence:  SNPSAP reuse conditions (https://www.infosubvenciones.es/bdnstrans/GE/es/avisolegal).
          Commercial reuse is allowed. Data about individuals may only be reused to scrutinise
          public administration, or after anonymisation for statistics or research.

So this module keeps legal entities only. A record is kept when its beneficiary starts with a
legal-entity tax ID (NIF: a letter A-H, J, N, P-S, U-W, then 7 digits and a check character).
Individuals (masked DNI such as ***2057**, NIE, or anything else) are dropped before anything is
stored, and only an allowlist of fields is kept.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from ..http import PoliteClient

API_URL = "https://www.infosubvenciones.es/bdnstrans/api/concesiones/busqueda"
ATTRIBUTION = ("Origen de los datos: Intervención General de la Administración del Estado (SNPSAP). "
               "Personas físicas eliminadas por law-radar: solo se conservan personas jurídicas.")
PAGE_SIZE = 50

COMPANY_NIF = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
# Fields kept for each company record. The beneficiary is split into tax ID and company name.
KEEP = ["codConcesion", "fechaConcesion", "importe", "ayudaEquivalente", "instrumento", "convocatoria",
        "numeroConvocatoria", "nivel1", "nivel2", "nivel3"]


def split_beneficiary(value: Optional[str]) -> Tuple[str, str]:
    """"B57456709 OLIVARES SL" -> ("B57456709", "OLIVARES SL")."""
    parts = (value or "").strip().split(None, 1)
    return (parts[0].upper(), parts[1].strip()) if parts else ("", "")


def is_company(tax_id: str) -> bool:
    return bool(COMPANY_NIF.match(tax_id))


def company_only(records: Iterable[Dict]) -> Tuple[List[Dict], int]:
    """Company rows with the allowlisted fields, and the number of rows dropped."""
    kept: List[Dict] = []
    dropped = 0
    for rec in records:
        tax_id, name = split_beneficiary(rec.get("beneficiario"))
        if not is_company(tax_id):
            dropped += 1                                   # never stored, never logged by name
            continue
        row = {"tax_id": tax_id, "company": name}
        row.update({k: rec.get(k) for k in KEEP})
        kept.append(row)
    return kept, dropped


def _fmt(day: dt.date) -> str:
    return day.strftime("%d/%m/%Y")


def fetch(client: PoliteClient, since: Optional[dt.date] = None, until: Optional[dt.date] = None,
          text: Optional[str] = None, call_number: Optional[str] = None, max_pages: int = 5) -> Iterator[Dict]:
    """Raw records page by page. Callers must pass them through company_only() before storing."""
    params = {"pageSize": str(PAGE_SIZE)}
    if since:
        params["fechaDesde"] = _fmt(since)
    if until:
        params["fechaHasta"] = _fmt(until)
    if text:
        params["descripcion"] = text
    if call_number:
        params["numeroConvocatoria"] = call_number
    for page in range(max_pages):
        resp = client.get(API_URL, params={**params, "page": str(page)}, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        yield from data.get("content", [])
        if data.get("last", True):
            break


def export_csv(rows: List[Dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# {ATTRIBUTION}\n")
        writer = csv.DictWriter(f, fieldnames=["tax_id", "company"] + KEEP)
        writer.writeheader()
        writer.writerows(rows)
    return path
