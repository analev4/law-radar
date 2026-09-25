"""Golden tests: real texts, recorded model responses, full pipeline.

Record once with `law-radar record-fixtures` (needs ANTHROPIC_API_KEY). CI sets
LAW_RADAR_REQUIRE_RECORDINGS=1, so a missing recording fails there instead of skipping.
"""
import datetime as dt
import os

import pytest

from law_radar.config import ROOT
from law_radar.fixtures import (EU_IRRELEVANT, EU_RELEVANT, FR_EXCLUDED, FR_IRRELEVANT, FR_RELEVANT,
                                GOLDEN_TODAY, golden_sources, load_eu, load_fr)
from law_radar.llm import LLM
from law_radar.models import NOT_GENERATED, CitationOut, Entry, FactOut
from law_radar.pipeline import run_pipeline
from law_radar.publish.markdown import render
from law_radar.state import State
from law_radar.steps.keyword_filter import KeywordFilter
from law_radar.steps.lint import lint
from law_radar.steps.model_filter import model_filter
from law_radar.steps.score import points
from law_radar.steps.validate import check_fact
from law_radar.textnorm import statement_numbers


RECORDED = ROOT / "tests" / "fixtures" / "recorded"


def _need(*names):
    missing = [n for n in names if not (RECORDED / n).exists()]
    if missing:
        if os.environ.get("LAW_RADAR_REQUIRE_RECORDINGS") == "1":
            pytest.fail(f"missing recordings: {missing}")
        pytest.skip(f"no recordings yet ({', '.join(missing)}); run `law-radar record-fixtures`")


@pytest.fixture
def golden(cfg, datasets, tmp_path):
    _need(*(f"{step}__{doc}.json" for step in ("filter", "read", "score")
            for doc in (f"eu_{EU_RELEVANT}", f"fr_{FR_RELEVANT}")))
    llm = LLM(mode="replay", recordings=RECORDED)
    digest = run_pipeline(cfg, golden_sources(), State(tmp_path), today=GOLDEN_TODAY,
                          since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY,
                          datasets=datasets, llm=llm, log=lambda _: None)
    return digest


def _entry(digest) -> Entry:
    entries = {e.id: e for e in digest.entries}
    assert f"eu:{EU_RELEVANT}" in entries, "the Pay Transparency Directive must be flagged"
    return entries[f"eu:{EU_RELEVANT}"]


def test_pay_directive_is_flagged_with_the_transposition_deadline(golden):
    e = _entry(golden)
    deadline = [f for f in e.facts if f.date == dt.date(2026, 6, 7)]
    assert deadline, "the 7 June 2026 transposition deadline must be a cited fact"
    f = deadline[0]
    assert f.date_kind == "transposition_deadline"
    assert f.citation.article.replace("Article", "Art.").startswith("Art. 34")
    assert "7 June 2026" in f.citation.quote and f.citation.article_checked


def test_pay_directive_cites_the_article_5_pay_information_rule(golden):
    e = _entry(golden)
    art5 = [f for f in e.facts if f.citation.article.replace("Article", "Art.").startswith("Art. 5")]
    assert art5, "the salary-information obligation (Art. 5) must be cited"
    assert all(f.citation.article_checked for f in art5)
    joined = " ".join(" ".join(f.citation.quote.split()) for f in art5)
    assert "the initial pay or its range" in joined
    # How the obligation can be met: in the ad, before the interview, or otherwise.
    assert "in a published job vacancy notice, prior to the job interview or otherwise" in joined


def test_pay_directive_scorecard_and_recipe(golden):
    sc = _entry(golden).scorecard
    assert sc is not None
    assert sc.forcing_mechanism.verdict == "yes"
    # Art. 5 also allows pay information before the interview, so a missing range in an ad is not proof.
    assert sc.gap_evidence.verdict == "unclear"
    assert sc.points == points(sc.forcing_mechanism.verdict, sc.findable.verdict, sc.early.verdict,
                               sc.gap_evidence.verdict, sc.crowding.verdict)
    recipes = _entry(golden).list_recipes
    job_ads = [r for r in recipes if r.dataset_id == "fr_france_travail_offres"]
    assert job_ads, "a recipe must look for job ads without a salary range"
    assert job_ads[0].signal_strength == "weak" and job_ads[0].caveat


def test_every_published_fact_still_validates(golden):
    docs = {f"eu:{EU_RELEVANT}": load_eu(EU_RELEVANT)}
    docs.update({d.id: d for d in load_fr()})
    for e in golden.entries:
        for f in e.facts:
            again, reason = check_fact(docs[e.id], FactOut(
                id=f.id, kind=f.kind, statement=f.statement, date=f.date.isoformat() if f.date else None,
                date_kind=f.date_kind, citation=CitationOut(article=f.citation.article, quote=f.citation.quote)))
            assert again is not None, f"{e.id} {f.id}: {reason}"


def test_every_published_sentence_passes_the_linter(golden):
    for e in golden.entries:
        _lint_entry(e)


def _lint_entry(e):
    fields = [("headline", e.headline.text, 1), ("who", e.who.text, 1), ("money", e.money.text, 1),
              ("confidence", e.confidence.reason, 1)]
    fields += [(f"what_changed_{i}", s.text, 1) for i, s in enumerate(e.what_changed, 1)]
    fields += [(f"fact {f.id}", f.statement, 1) for f in e.facts]
    for key in ("forcing_mechanism", "findable", "early", "gap_evidence", "crowding"):
        fields.append((key, getattr(e.scorecard, key).evidence, 1))
    for name, text, n in fields:
        if text != NOT_GENERATED:
            assert lint(text, n) == [], f"{name}: {text}"


def test_fisheries_is_rejected(cfg, golden):
    assert f"eu:{EU_IRRELEVANT}" not in {e.id for e in golden.entries}
    # Layer 1: the keyword filter drops it for free.
    assert not KeywordFilter(cfg).match(load_eu(EU_IRRELEVANT, with_text=False)).passed
    # Layer 2: the small model says no as well.
    _need(f"filter__eu_{EU_IRRELEVANT}.json")
    verdict = model_filter(LLM(mode="replay", recordings=RECORDED), cfg, load_eu(EU_IRRELEVANT))
    assert verdict.relevant is False


def test_golden_digest_renders(golden):
    md = render(golden)
    assert md.startswith("# Law radar: week 40")
    assert "Not legal advice" in md and "Scorecard (" in md and "List recipes (hypotheses to test)" in md


# ---------------------------------------------------------------------------
# France: Décret n° 2026-168 (apprentice hiring aid)
# ---------------------------------------------------------------------------

def test_apprentice_decree_is_flagged_with_the_aid_amounts(golden):
    entries = {e.id: e for e in golden.entries}
    assert f"fr:{FR_RELEVANT}" in entries, "the apprentice aid decree must be flagged"
    e = entries[f"fr:{FR_RELEVANT}"]
    by_amount = {}
    for f in e.facts:
        for n in statement_numbers(f.statement):
            by_amount.setdefault(n, []).append(f)
    for amount in ("4500", "2000", "1500", "750", "6000"):
        assert amount in by_amount, f"the €{amount} amount must be a cited fact"
        assert any(f.citation.article.lower().startswith(("article 1", "art. 1")) and f.citation.article_checked
                   for f in by_amount[amount]), f"€{amount} must be cited from Article 1"
    assert e.language == "fr" and e.url.startswith("https://www.legifrance.gouv.fr/jorf/id/")


def test_french_texts_that_must_not_be_flagged(golden):
    ids = {e.id for e in golden.entries}
    assert f"fr:{FR_IRRELEVANT}" not in ids          # label rouge: no keyword match
    assert f"fr:{FR_EXCLUDED}" not in ids            # naturalisation: never read at all
