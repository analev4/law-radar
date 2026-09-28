"""BDNS grants: companies kept, individuals dropped before anything is stored.

The records below are made up. The formats (tax ID + name, masked ID for individuals) copy what the
live API returned on 28 September 2026; no real person's data is in this file.
"""
import datetime as dt

from law_radar.datasets import bdns

RECORDS = [
    {"beneficiario": "B00000000 EMPRESA FICTICIA SL", "codConcesion": "SB1", "fechaConcesion": "2026-09-25",
     "importe": 13456, "instrumento": "SUBVENCIÓN", "convocatoria": "Ayudas a la contratación",
     "numeroConvocatoria": "800001", "nivel1": "AUTONOMICA", "nivel2": "ILLES BALEARS", "nivel3": "X",
     "idPersona": 1, "urlBR": "https://example"},
    {"beneficiario": "***1234** NOMBRE APELLIDO FICTICIO", "codConcesion": "SB2", "importe": 3271.46},
    {"beneficiario": "X1234567L PERSONA FICTICIA", "codConcesion": "SB3", "importe": 100},
    {"beneficiario": "12345678Z PERSONA FICTICIA", "codConcesion": "SB4", "importe": 100},
    {"beneficiario": "G00000000 ASOCIACION FICTICIA", "codConcesion": "SB5", "importe": 134000},
    {"beneficiario": None, "codConcesion": "SB6"},
]


def test_only_legal_entities_are_kept():
    rows, dropped = bdns.company_only(RECORDS)
    assert [r["tax_id"] for r in rows] == ["B00000000", "G00000000"]
    assert dropped == 4
    assert rows[0]["company"] == "EMPRESA FICTICIA SL"
    # Allowlisted fields only: no internal person ID, no links.
    assert set(rows[0]) == {"tax_id", "company"} | set(bdns.KEEP)
    assert "idPersona" not in rows[0] and "urlBR" not in rows[0]


def test_company_tax_id_rule():
    assert bdns.is_company("B57456709") and bdns.is_company("G64816515") and bdns.is_company("Q2826000H")
    for not_company in ("***2057**", "12345678Z", "X1234567L", "K1234567A", "B123", ""):
        assert not bdns.is_company(not_company)


def test_csv_carries_the_attribution(tmp_path):
    rows, _ = bdns.company_only(RECORDS)
    text = bdns.export_csv(rows, tmp_path / "grants.csv").read_text()
    assert text.startswith("# Origen de los datos: Intervención General de la Administración del Estado")
    assert "Personas físicas eliminadas" in text and "FICTICIO" not in text


def test_fetch_builds_the_query():
    calls = []

    class Resp:
        def __init__(self, last):
            self._last = last

        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"beneficiario": "B00000000 EMPRESA FICTICIA SL"}], "last": self._last}

    class Client:
        def get(self, url, params=None, headers=None):
            calls.append(params)
            return Resp(last=len(calls) == 2)

    out = list(bdns.fetch(Client(), since=dt.date(2026, 9, 1), until=dt.date(2026, 9, 2), text="contratación"))
    assert len(out) == 2 and [c["page"] for c in calls] == ["0", "1"]
    assert calls[0]["fechaDesde"] == "01/09/2026" and calls[0]["descripcion"] == "contratación"
