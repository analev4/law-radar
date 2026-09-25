"""Find EU directives that a national text says it transposes.

EU law requires national transposition measures to reference the directive (for example
Art. 34(2) of Directive 2023/970), so a sentence that both mentions transposition and names a
directive is a reliable signal. A directive merely cited in the visas ("Vu la directive...") is
not counted.
"""
from __future__ import annotations

import re
from typing import List

_DIRECTIVE = re.compile(
    r"directiv[ae]\s*(?:\((?:UE|CE|EU|EC)\)\s*)?(?:n[°º]\s*|no\.?\s*)?(\d{4})/(\d{1,4})",
    re.IGNORECASE,
)
_TRANSPOSES = re.compile(r"transpos|transpon|incorpor", re.IGNORECASE)


def transposed_directives(text: str) -> List[str]:
    """CELEX numbers (e.g. 32023L0970) of directives named in a sentence about transposition."""
    found: List[str] = []
    for segment in re.split(r"(?<=[.;:])\s+|\n", text):
        if not _TRANSPOSES.search(segment):
            continue
        for year, num in _DIRECTIVE.findall(segment):
            celex = f"3{year}L{int(num):04d}"
            if celex not in found:
                found.append(celex)
    return found
