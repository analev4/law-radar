"""Shared prompt context: the ICP and the dataset catalogue, rendered as plain text.

Kept stable across calls in a run so the system prompt can be cached.
"""
from __future__ import annotations

from typing import Dict, Iterable

from ..config import Config, Dataset
from ..llm import prompt


def icp_text(cfg: Config) -> str:
    icp = cfg.icp
    sectors = "; ".join(
        s.label + (f" (NACE {s.nace}" if s.nace else "") + (f", NAF {s.naf}" if s.naf else "")
        + (f", CNAE {s.cnae}" if s.cnae else "") + (")" if s.nace else "")
        for s in icp.sectors
    )
    return (
        "# ICP\n"
        f"- Company: {icp.name}. {icp.description}\n"
        f"- Markets: {', '.join(icp.markets)}\n"
        f"- Sectors: {sectors}\n"
        f"- Company size bands (staff): {', '.join(icp.size_bands)}\n"
        f"- Buyer roles: {', '.join(icp.buyer_roles)}\n"
        f"- Topics: {', '.join(icp.topics)}\n"
    )


def datasets_text(datasets: Dict[str, Dataset], markets: Iterable[str]) -> str:
    wanted = set(markets) | {"EU"}
    lines = ["# Dataset catalogue"]
    for d in datasets.values():
        if d.market not in wanted:
            continue
        lines.append(
            f"- id: {d.id}\n  name: {d.name} ({d.publisher}, {d.market})\n  access: {d.access}\n"
            f"  names companies: {'yes' if d.names_companies else 'no'}\n  timing: {d.timing}\n"
            f"  fields: {', '.join(d.fields)}\n  notes: {d.notes or 'none'}"
        )
    return "\n".join(lines)


def system_prompt(task: str, cfg: Config, extra: str = "") -> str:
    parts = [prompt("style"), prompt(task), icp_text(cfg)]
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)
