"""Turn model output into a published Entry.

Every model-written field goes through the citation checks and the linter. A failing field is
rewritten once with the errors fed back. A second failure drops it and marks it "not generated".
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..config import Config, Dataset
from ..llm import LLM, LLMError, MissingRecording, Pending
from ..models import (NOT_GENERATED, Confidence, Deadline, Document, Entry, Fact, FactOut, ListRecipe,
                      ReadOutput, RewriteOutput, Scorecard, ScoreLine, ScoreOutput, Sentence, When, Who)
from ..textnorm import digit_numbers
from .context import system_prompt
from .lint import lint
from .score import MAX_POINTS, points
from .validate import check_fact, check_sentence, validate_facts

DEADLINE_LABELS = {
    "transposition_deadline": "Transposition deadline",
    "deadline": "Deadline",
    "application": "Applies from",
}


@dataclass
class Stats:
    facts_dropped: int = 0
    fields_not_generated: int = 0
    drop_reasons: List[Tuple[str, str]] = field(default_factory=list)


class Assembler:
    def __init__(self, llm: LLM, cfg: Config, datasets: Dict[str, Dataset], today: dt.date):
        self.llm = llm
        self.cfg = cfg
        self.datasets = datasets
        self.today = today
        # Exchange mode: requests still waiting for an answer in the current phase.
        self.waiting: List[MissingRecording] = []
        # Numbers a sentence may use without a fact behind them: the ICP's own size bands and codes.
        icp_values = cfg.icp.size_bands + [c for s in cfg.icp.sectors for c in (s.nace, s.naf, s.cnae) if c]
        self.icp_numbers: Set[str] = {n.lstrip("0") or "0" for v in icp_values for n in re.findall(r"\d+", v)}

    # -- field repair -------------------------------------------------------

    def _errors(self, text: str, refs: List[str], facts: Dict[str, Fact], sentences: Optional[int],
                extra: Optional[Set[str]], check_numbers: bool) -> List[str]:
        errs = lint(text, sentences)
        if check_numbers:
            errs += check_sentence(text, refs, facts, extra)
        return errs

    def fix(self, doc: Document, name: str, text: str, refs: List[str], facts: Dict[str, Fact],
            sentences: Optional[int] = 1, extra: Optional[Set[str]] = None,
            check_numbers: bool = True) -> Optional[Tuple[str, List[str]]]:
        """(text, fact_refs) that pass the checks, or None. One rewrite with the errors fed back."""
        live = [r for r in refs if r in facts]            # a dropped fact can't be cited again
        errs = self._errors(text, refs, facts, sentences, extra, check_numbers)
        if not errs:
            return text.strip(), live
        # The rewriter sees every validated fact of this law, so it can cite the fact a number comes
        # from instead of deleting a correct number.
        known = [{"id": f.id, "statement": f.statement, "quote": f.citation.quote} for f in facts.values()]
        user = (
            f"Field: {name}\nRequired sentences: {sentences if sentences else 'a short phrase'}\n"
            f"Current text: {text}\nFacts it cited: {', '.join(refs) if refs else 'none'}\n"
            f"Errors:\n- " + "\n- ".join(errs) + "\n\n"
            f"Validated facts of this law (cite the ones you rely on in fact_refs):\n"
            f"{json.dumps(known, ensure_ascii=False, indent=1)}"
        )
        try:
            out = self.llm.structured(step="rewrite", key=f"{doc.id}__{name}", model=self.cfg.models.read,
                                      system=system_prompt("rewrite", self.cfg), user=user,
                                      output=RewriteOutput, max_tokens=2000, effort="low")
        except MissingRecording as exc:       # collect, so one round asks for every rewrite at once
            self.waiting.append(exc)
            return None
        except LLMError:
            return None
        new_refs = [r for r in out.fact_refs if r in facts]
        if self._errors(out.text, new_refs, facts, sentences, extra, check_numbers):
            return None
        return out.text.strip(), new_refs

    def raise_if_waiting(self) -> None:
        if self.waiting:
            waiting, self.waiting = self.waiting, []
            cls = Pending if any(isinstance(w, Pending) for w in waiting) else MissingRecording
            raise cls("; ".join(str(w) for w in waiting))

    # -- facts --------------------------------------------------------------

    def facts(self, doc: Document, raw: List[FactOut], stats: Stats) -> Dict[str, Fact]:
        kept, dropped = validate_facts(doc, raw)
        stats.drop_reasons.extend(dropped)
        by_id: Dict[str, Fact] = {}
        for f in kept:
            if lint(f.statement, 1):
                raw_f = next(r for r in raw if r.id == f.id)
                self_ref = {f.id: f}
                fixed = self.fix(doc, f"fact_{f.id}", f.statement, [f.id], self_ref)
                new = fixed[0] if fixed else None
                if new is None:
                    stats.drop_reasons.append((f.id, "statement failed the writing checks twice"))
                    continue
                rechecked, reason = check_fact(doc, raw_f.model_copy(update={"statement": new}))
                if rechecked is None:
                    stats.drop_reasons.append((f.id, f"rewritten statement failed: {reason}"))
                    continue
                f = rechecked
            by_id[f.id] = f
        self.raise_if_waiting()
        stats.facts_dropped += len(raw) - len(by_id)
        return by_id

    # -- entry --------------------------------------------------------------

    def sentence(self, doc: Document, name: str, text: str, refs: List[str], facts: Dict[str, Fact],
                 not_generated: List[str], extra: Optional[Set[str]] = None) -> Sentence:
        fixed = self.fix(doc, name, text, refs, facts, 1, extra)
        if fixed is None:
            not_generated.append(name)
            return Sentence(text=NOT_GENERATED, fact_refs=[])
        return Sentence(text=fixed[0], fact_refs=fixed[1])

    def when(self, doc: Document, facts: Dict[str, Fact]) -> When:
        eif = doc.entry_into_force
        deadlines: List[Deadline] = []
        for f in facts.values():
            if not f.date:
                continue
            if f.date_kind == "entry_into_force" and eif is None:
                eif = f.date
            if f.date_kind in DEADLINE_LABELS:
                deadlines.append(Deadline(date=f.date, label=DEADLINE_LABELS[f.date_kind], fact_ref=f.id))
        deadlines.sort(key=lambda d: d.date)
        upcoming = [d.date for d in deadlines if d.date >= self.today]
        return When(publication=doc.published, entry_into_force=eif, deadlines=deadlines,
                    next_deadline=upcoming[0] if upcoming else None)

    def scorecard(self, doc: Document, out: ScoreOutput, facts: Dict[str, Fact],
                  not_generated: List[str]) -> Tuple[Scorecard, List[ListRecipe]]:
        lines = {}
        for name in ("forcing_mechanism", "findable", "early", "gap_evidence", "crowding"):
            line = getattr(out, name)
            extra = self.icp_numbers | self._dataset_numbers(line.dataset_ids)
            fixed = self.fix(doc, f"scorecard_{name}", line.evidence, line.fact_refs, facts, 1, extra)
            if fixed is None:
                not_generated.append(f"scorecard.{name}")
                fixed = (NOT_GENERATED, [])
            lines[name] = ScoreLine(verdict=line.verdict, evidence=fixed[0], fact_refs=fixed[1],
                                    dataset_ids=line.dataset_ids)
        total = points(*(lines[n].verdict for n in ("forcing_mechanism", "findable", "early", "gap_evidence", "crowding")))
        card = Scorecard(**lines, points=total, max_points=MAX_POINTS,
                         sinks=lines["forcing_mechanism"].verdict == "no")

        recipes: List[ListRecipe] = []
        # A recipe applies the whole law to a dataset, so its numbers may come from any validated fact
        # of this law, the ICP or the catalogue entry. Nothing else.
        all_refs = list(facts)
        for i, r in enumerate(out.list_recipes[:3], 1):
            extra = self.icp_numbers | self._dataset_numbers([r.dataset_id])
            parts = {}
            for part in ("filter", "gap_evidence", "metric"):
                fixed = self.fix(doc, f"recipe{i}_{part}", getattr(r, part), all_refs, facts, None, extra)
                parts[part] = fixed[0] if fixed else None
            caveat = None
            if r.caveat:
                fixed = self.fix(doc, f"recipe{i}_caveat", r.caveat, all_refs, facts, 1, extra)
                caveat = fixed[0] if fixed else None
            if any(v is None for v in parts.values()):
                not_generated.append(f"list_recipes[{i}]")
                continue
            ds = self.datasets.get(r.dataset_id)
            recipes.append(ListRecipe(
                dataset_id=r.dataset_id, dataset_name=ds.name if ds else r.dataset_id,
                dataset_url=ds.url if ds else None, dataset_verified=ds is not None,
                filter=parts["filter"], gap_evidence=parts["gap_evidence"], metric=parts["metric"],
                signal_strength=r.signal_strength, caveat=caveat,
            ))
        return card, recipes

    def _dataset_numbers(self, ids: List[str]) -> Set[str]:
        nums: Set[str] = set()
        for i in ids:
            d = self.datasets.get(i)
            if d:
                nums |= digit_numbers(" ".join([d.name, d.timing, d.notes or "", " ".join(d.fields)]))
        return nums

    def build(self, doc: Document, read: ReadOutput, facts: Dict[str, Fact],
              score_out: Optional[ScoreOutput], stats: Stats) -> Optional[Entry]:
        """facts: the output of self.facts(), computed once and shared with the score step."""
        if not facts:
            return None          # nothing survived the citation checks: publish nothing for this text
        ng: List[str] = []

        headline = self.sentence(doc, "headline", read.headline.text, read.headline.fact_refs, facts, ng)
        what_changed = []
        items = list(read.what_changed[:2])
        for i in range(2):
            if i < len(items):
                what_changed.append(self.sentence(doc, f"what_changed_{i + 1}", items[i].text,
                                                  items[i].fact_refs, facts, ng))
            else:
                ng.append(f"what_changed_{i + 1}")
                what_changed.append(Sentence(text=NOT_GENERATED))
        who_s = self.sentence(doc, "who", read.who.text, read.who.fact_refs, facts, ng, self.icp_numbers)
        money = self.sentence(doc, "money", read.money.text, read.money.fact_refs, facts, ng)
        fixed = self.fix(doc, "confidence_reason", read.confidence.reason, [], facts, 1, check_numbers=False)
        reason = fixed[0] if fixed else None
        if reason is None:
            ng.append("confidence.reason")
        confidence = Confidence(level=read.confidence.level, reason=reason or NOT_GENERATED)

        card, recipes = (None, [])
        if score_out is not None:
            card, recipes = self.scorecard(doc, score_out, facts, ng)

        self.raise_if_waiting()
        stats.fields_not_generated += len(ng)
        return Entry(
            id=doc.id, market=doc.market, doc_type=doc.doc_type, title_original=doc.title,
            language=doc.language, published=doc.published, url=doc.url, text_url=doc.text_url,
            text_sha256=hashlib.sha256(doc.text.encode("utf-8")).hexdigest(),
            transposes=sorted(set(doc.transposes) | set(read.transposes)),
            headline=headline, what_changed=what_changed,
            who=Who(text=who_s.text, fact_refs=who_s.fact_refs, icp_match=read.icp_match),
            when=self.when(doc, facts), money=money, facts=list(facts.values()),
            scorecard=card, list_recipes=recipes, confidence=confidence, not_generated=ng,
        )
