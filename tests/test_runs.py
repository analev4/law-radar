"""Whole-pipeline behaviour that needs no model: empty week, --no-ai mode, schema, state."""
import datetime as dt
import json

from law_radar.config import ROOT
from law_radar.fixtures import GOLDEN_TODAY, FixtureSource, eu_fixture_source
from law_radar.models import Digest
from law_radar.pipeline import run_pipeline
from law_radar.publish.files import write
from law_radar.publish.markdown import render
from law_radar.state import State


class NoModel:
    """Fails the test if anything tries to call a model."""

    def __init__(self):
        from law_radar.cost import CostTracker
        self.tracker = CostTracker()
        self.generator = "replay"

    def structured(self, **kwargs):
        raise AssertionError("a model was called")


def run(cfg, datasets, sources, tmp_path, no_ai=False, llm=None):
    return run_pipeline(cfg, sources, State(tmp_path / "state"), today=GOLDEN_TODAY,
                        since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY,
                        datasets=datasets, llm=llm, no_ai=no_ai, log=lambda _: None)


def test_empty_week_is_one_line(cfg, datasets, tmp_path):
    digest = run(cfg, datasets, [FixtureSource("eu", "EU", [])], tmp_path, llm=NoModel())
    assert digest.nothing_relevant
    md = render(digest)
    assert md.splitlines()[0] == "Law radar, week 40: nothing relevant this week."
    assert "Not legal advice" in md
    assert len([line for line in md.splitlines() if line.strip()]) == 2   # the line and the disclaimer


def test_week_with_only_irrelevant_texts_is_empty(cfg, datasets, tmp_path):
    from law_radar.fixtures import EU_IRRELEVANT, load_eu
    digest = run(cfg, datasets, [FixtureSource("eu", "EU", [load_eu(EU_IRRELEVANT)])], tmp_path, llm=NoModel())
    assert digest.nothing_relevant and digest.run.counts.fetched == 1


def test_no_ai_lists_keyword_matches_without_calling_a_model(cfg, datasets, tmp_path):
    digest = run(cfg, datasets, [eu_fixture_source()], tmp_path, no_ai=True, llm=None)
    assert digest.mode == "no-ai"
    assert [e.id for e in digest.entries] == ["eu:32023L0970"]
    e = digest.entries[0]
    assert e.url.endswith("CELEX:32023L0970") and e.matched_codes
    md, js = write(digest, tmp_path / "out")
    assert "keyword mode, no summaries" in md.read_text()
    assert Digest.model_validate_json(js.read_text()).entries[0].kind == "no-ai"


def test_state_dedupes_across_runs(cfg, datasets, tmp_path):
    state = State(tmp_path / "state")
    kwargs = dict(today=GOLDEN_TODAY, since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY,
                  datasets=datasets, no_ai=True, log=lambda _: None)
    first = run_pipeline(cfg, [eu_fixture_source()], state, **kwargs)
    state.save(GOLDEN_TODAY, GOLDEN_TODAY)
    second = run_pipeline(cfg, [eu_fixture_source()], State.load(tmp_path / "state"), **kwargs)
    assert len(first.entries) == 1 and second.nothing_relevant
    saved = json.loads((tmp_path / "state" / "seen.json").read_text())
    assert set(saved["seen"]) == {"eu:32023L0970", "eu:32026R1933"}      # IDs only


def test_schema_file_matches_models():
    on_disk = json.loads((ROOT / "schema" / "digest.schema.json").read_text())
    assert on_disk == Digest.model_json_schema(), "run `law-radar schema` and commit the result"



def test_second_run_in_the_same_week_merges(cfg, datasets, tmp_path):
    from law_radar.publish.files import write, write_matches
    out = tmp_path / "digests"
    state = State(tmp_path / "state")
    kwargs = dict(today=GOLDEN_TODAY, since=GOLDEN_TODAY - dt.timedelta(days=7), until=GOLDEN_TODAY,
                  datasets=datasets, no_ai=True, log=lambda _: None)
    docs = []
    first = run_pipeline(cfg, [eu_fixture_source()], state, matches_out=docs, **kwargs)
    write(first, out)
    write_matches(first, docs, out)
    # Second run the same week: everything is already seen, so it finds nothing new.
    docs2 = []
    second = run_pipeline(cfg, [eu_fixture_source()], state, matches_out=docs2, **kwargs)
    assert second.nothing_relevant
    md, js = write(second, out)
    write_matches(second, docs2, out)
    merged = Digest.model_validate_json(js.read_text())
    assert [e.id for e in merged.entries] == ["eu:32023L0970"] and not merged.nothing_relevant
    assert "nothing relevant" not in md.read_text()
    matches = json.loads((out / "2026-40.matches.json").read_text())
    assert [d["id"] for d in matches["documents"]] == ["eu:32023L0970"]
