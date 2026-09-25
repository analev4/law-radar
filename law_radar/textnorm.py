"""Text normalisation shared by the source adapters and the citation validator."""
from __future__ import annotations

import re
import unicodedata
from typing import Set

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
}
_DASHES = {c: "-" for c in "‐‑‒–—―−"}


def clean(text: str) -> str:
    """Light normalisation used for stored text: NFKC, one space between words, trimmed lines."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u202f", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def canon(text: str) -> str:
    """Aggressive normalisation used only to compare a quote with a document."""
    text = unicodedata.normalize("NFKC", text)
    for a, b in {**_QUOTES, **_DASHES}.items():
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text)
    # "1 er", "1 re" come from stripped <sup> tags in French texts.
    text = re.sub(r"(\d) (er|re|ère|o|a)\b", r"\1\2", text)
    return text.strip()


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_ARTICLE_REF = re.compile(
    r"\b(?:(?:final|transitional|additional|repealing|derogatory)\s+provisions?|provisions?|"
    r"disposici[oó]n(?:es)?(?:\s+(?:final|transitoria|adicional|derogatoria)(?:es)?)?|dispositions?|"
    r"art(?:icle|ículo|iculo)?s?\.?|annex(?:e)?|anexo|recital|considérant|para(?:graph)?\.?|"
    r"regulation|directive|decree|décret|decret|real decreto|ley|loi|order|orden|arrêté|n°|no\.)"
    r"\s*(?:\(?(?:eu|ue|ce|ec)\)?\s*)?(?:(?:no\.?|n°|nº)\s*)?[\dA-Z][\w./()-]*"
    # a list of further article numbers: "Art. 9(3), 23(2) and 24"
    r"(?:\s*(?:,|and|or|et|ou|y|o)\s*\d+[a-z]?(?:\(\w+\))*)*",
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"\d{1,3}(?:[ .,'\u00a0\u202f]\d{3})+(?!\d)|\d+(?:[.,]\d+)?")
_THOUSANDS_RE = re.compile(r"\d{1,3}(?:[ .,'\u00a0\u202f]\d{3})+")


def strip_references(text: str) -> str:
    """Remove article and act references so "Art. 34" or "Directive 2023/970" don't count as figures."""
    return _ARTICLE_REF.sub(" ", text)


def digit_numbers(text: str) -> Set[str]:
    out: Set[str] = set()
    for m in _NUM_RE.finditer(text):
        tok = m.group()
        if _THOUSANDS_RE.fullmatch(tok):
            out.add(re.sub(r"\D", "", tok))
        else:
            tok = tok.replace(",", ".")
            if "." in tok:
                tok = tok.rstrip("0").rstrip(".") or "0"
            out.add(tok.lstrip("0") or "0")
    return out


_UNITS = {
    # English
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    # French
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15,
    "seize": 16, "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
    # Spanish
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21,
    "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
    "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300,
    "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700, "setecientas": 700,
    "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900,
}
_HUNDRED = {"hundred", "cent", "cents"}
_THOUSAND = {"thousand", "mille", "mil"}
_CONNECTORS = {"and", "et", "y"}


def _words_to_numbers(text: str) -> Set[str]:
    """Convert runs of number words (EN/FR/ES) into digits. Used on quotes only, so it can be generous."""
    out: Set[str] = set()
    tokens = re.findall(r"[a-zà-ÿ]+", strip_accents(text.lower()).replace("-", " "))
    total, current, in_run, prev = 0, 0, False, ""

    def flush():
        nonlocal total, current, in_run
        if in_run:
            out.add(str(total + current))
        total, current, in_run = 0, 0, False

    for tok in tokens:
        if tok in _UNITS:
            val = _UNITS[tok]
            if tok in ("vingt", "vingts") and prev == "quatre":
                current += 80 - 4           # quatre-vingt = 80
            else:
                current += val              # Spanish hundreds (doscientos...) are additive too
            in_run = True
        elif tok in _HUNDRED:
            current = (current or 1) * 100
            in_run = True
        elif tok in _THOUSAND:
            total += (current or 1) * 1000
            current = 0
            in_run = True
        elif tok in _CONNECTORS and in_run:
            pass
        else:
            flush()
        prev = tok
    flush()
    return out


def quote_numbers(text: str) -> Set[str]:
    """All numbers a quote supports: digits plus number words."""
    return digit_numbers(text) | _words_to_numbers(text)


def statement_numbers(text: str) -> Set[str]:
    """Numbers a model-written sentence asserts (digits only, references removed)."""
    return digit_numbers(strip_references(text))


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

_MONTHS = {
    1: ["january", "janvier", "enero"], 2: ["february", "fevrier", "febrero"],
    3: ["march", "mars", "marzo"], 4: ["april", "avril", "abril"], 5: ["may", "mai", "mayo"],
    6: ["june", "juin", "junio"], 7: ["july", "juillet", "julio"], 8: ["august", "aout", "agosto"],
    9: ["september", "septembre", "septiembre", "setiembre"], 10: ["october", "octobre", "octubre"],
    11: ["november", "novembre", "noviembre"], 12: ["december", "decembre", "diciembre"],
}
_MONTH_LOOKUP = {name: num for num, names in _MONTHS.items() for name in names}


def months(text: str) -> Set[int]:
    words = re.findall(r"[a-z]+", strip_accents(text.lower()))
    found = {_MONTH_LOOKUP[w] for w in words if w in _MONTH_LOOKUP}
    # "may" is also an English verb; only count it next to a number.
    if 5 in found and not re.search(r"\d\s+may\b|\bmay\s+\d", strip_accents(text.lower())):
        if not ({"mai", "mayo"} & set(words)):
            found.discard(5)
    return found
