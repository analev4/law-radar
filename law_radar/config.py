"""Load and validate the ICP config and the dataset catalogue.

The ICP comes from the ICP_YAML environment variable (filled from a repository secret) or from
icp.yaml. Nothing ICP-specific lives anywhere else in the code.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


class Sector(BaseModel):
    label: str
    nace: Optional[str] = None
    naf: Optional[str] = None
    cnae: Optional[str] = None


class ICP(BaseModel):
    name: str
    description: str
    markets: List[str]
    sectors: List[Sector]
    size_bands: List[str]
    buyer_roles: List[str]
    topics: List[str]


class EUSource(BaseModel):
    enabled: bool = True
    eurovoc: List[str] = Field(default_factory=list)
    directory_prefixes: List[str] = Field(default_factory=list)
    include_corrigenda: bool = False


class FRSource(BaseModel):
    enabled: bool = False
    natures: List[str] = Field(default_factory=lambda: ["LOI", "ORDONNANCE", "DECRET", "ARRETE"])
    # Sections about named people: appointments, naturalisations. Never read (no personal data).
    exclude_headings: List[str] = Field(default_factory=lambda: ["Mesures nominatives", "Naturalisations"])


class ESSource(BaseModel):
    enabled: bool = False
    sections: List[str] = Field(default_factory=lambda: ["1"])      # section 2 (named people) is never read
    # Section 3 is read only under these epigraphs; the rest of it is grants, prizes and similar acts.
    section3_epigraphs: List[str] = Field(default_factory=lambda: ["Convenios colectivos de trabajo"])
    materias: List[str] = Field(default_factory=list)                # BOE subject codes that count as a match


class Sources(BaseModel):
    eu: EUSource = Field(default_factory=EUSource)
    fr: FRSource = Field(default_factory=FRSource)
    es: ESSource = Field(default_factory=ESSource)


class Watch(BaseModel):
    directives: List[str] = Field(default_factory=list)


class Channel(BaseModel):
    enabled: bool = False


class Delivery(BaseModel):
    issue: bool = True
    pages: bool = True
    slack: Channel = Field(default_factory=Channel)
    email: Channel = Field(default_factory=Channel)
    notion: Channel = Field(default_factory=Channel)


class Limits(BaseModel):
    max_documents_per_run: int = 25          # API mode: cost cap, applied before any model call
    max_documents_claude_code: int = 10      # /digest: texts read per week in Claude Code
    max_text_chars: int = 200_000


class Models(BaseModel):
    filter: str = "claude-haiku-4-5-20251001"
    read: str = "claude-sonnet-5"
    read_effort: str = "medium"


class Config(BaseModel):
    icp: ICP
    keywords: Dict[str, List[str]]          # per language code, plus "exclude"
    sources: Sources = Field(default_factory=Sources)
    watch: Watch = Field(default_factory=Watch)
    delivery: Delivery = Field(default_factory=Delivery)
    limits: Limits = Field(default_factory=Limits)
    models: Models = Field(default_factory=Models)
    sha256: str = ""


class Dataset(BaseModel):
    id: str
    market: str
    name: str
    publisher: str
    url: str
    access: str
    licence: str
    names_companies: bool
    timing: str
    fields: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    verified_on: str
    verified: str                           # what was checked, and against what


class ConfigError(Exception):
    pass


def load_config(path: Optional[str] = None) -> Config:
    raw = os.environ.get("ICP_YAML")
    origin = "ICP_YAML environment variable"
    if not raw:
        p = Path(path) if path else ROOT / "icp.yaml"
        if not p.exists():
            raise ConfigError(
                f"No config at {p}. Copy icp.example.yaml to icp.yaml and edit it, "
                "or set the ICP_YAML environment variable."
            )
        raw = p.read_text(encoding="utf-8")
        origin = str(p)
    try:
        data = yaml.safe_load(raw)
        cfg = Config.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - we want one clear message
        raise ConfigError(f"Invalid config in {origin}: {exc}") from exc
    cfg.sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return cfg


def load_datasets(path: Optional[str] = None) -> Dict[str, Dataset]:
    p = Path(path) if path else ROOT / "datasets.yaml"
    items = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    datasets = [Dataset.model_validate(i) for i in items]
    return {d.id: d for d in datasets}
