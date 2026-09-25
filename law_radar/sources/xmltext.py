"""Plain text from XML/XHTML elements, shared by the source adapters."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..textnorm import clean

BLOCK = {"p", "div", "td", "th", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "br", "dt", "dd"}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def text_of(el: ET.Element) -> str:
    parts: List[str] = []

    def walk(node: ET.Element) -> None:
        name = local(node.tag)
        if name in ("script", "style", "head"):
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if local(child.tag) in BLOCK:
                parts.append("\n")
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return clean("".join(parts))
