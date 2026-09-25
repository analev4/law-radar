"""Assembly rules with a stub model: dropped facts, one rewrite, then "not generated"."""
from law_radar.cost import CostTracker
from law_radar.fixtures import EU_RELEVANT, GOLDEN_TODAY, load_eu
from law_radar.models import (NOT_GENERATED, CitationOut, Confidence, FactOut, IcpMatch, ReadOutput,
                              RecipeOut, RewriteOutput, ScoreLineOut, ScoreOutput, SentenceOut)
from law_radar.steps.assemble import Assembler, Stats

ART34 = ("Member States shall bring into force the laws, regulations and administrative provisions "
         "necessary to comply with this Directive by 7 June 2026.")
ART5 = "such as in a published job vacancy notice, prior to the job interview or otherwise"


class StubLLM:
    def __init__(self, rewrites):
        self.rewrites = rewrites
        self.calls = []
        self.tracker = CostTracker()

    def structured(self, *, step, key, output, **kwargs):
        self.calls.append((step, key))
        assert step == "rewrite"
        field = key.split("__", 1)[1]
        text, refs = self.rewrites[field] if isinstance(self.rewrites[field], tuple) else (self.rewrites[field], [])
        return RewriteOutput(text=text, fact_refs=refs)


def s(text, refs):
    return SentenceOut(text=text, fact_refs=refs)


READ = ReadOutput(
    headline=s("EU countries must apply the pay transparency rules by 7 June 2026.", ["f1"]),
    what_changed=[
        s("Job applicants get the starting pay or its range, in the ad or before the interview.", ["f3"]),
        s("EU countries had to apply the rules by 1 January 2025.", ["f2"]),       # relies on a bad fact
    ],
    who=s("This crucial rule covers Ledgerly's 10-249 staff segment in France and Spain.", ["f3"]),
    icp_match=IcpMatch(countries=["FR", "ES"], sectors=["all"], size_bands=["10-49", "50-249"],
                       roles=["HR manager"], basis="inferred"),
    money=s("The text sets no penalty amount.", []),
    facts=[
        FactOut(id="f1", kind="date", statement="EU countries must transpose the Directive by 7 June 2026.",
                date="2026-06-07", date_kind="transposition_deadline",
                citation=CitationOut(article="Art. 34(1)", quote=ART34)),
        FactOut(id="f2", kind="date", statement="EU countries must apply the rules by 1 January 2025.",
                date="2025-01-01", date_kind="deadline",
                citation=CitationOut(article="Art. 34(1)", quote="by 1 January 2025 at the latest, Member States")),
        FactOut(id="f3", kind="obligation",
                statement="Employers must give applicants the starting pay or range, in the ad or before the interview.",
                date=None, date_kind=None, citation=CitationOut(article="Art. 5(1)", quote=ART5)),
    ],
    transposes=[],
    confidence=Confidence(level="high", reason="Every date and obligation is quoted from an article."),
)

SCORE = ScoreOutput(
    forcing_mechanism=ScoreLineOut(verdict="yes", evidence="EU countries must apply the rules by 7 June 2026.",
                                   fact_refs=["f1"], dataset_ids=[]),
    findable=ScoreLineOut(verdict="yes", evidence="France Travail job ads name the employer.",
                          fact_refs=[], dataset_ids=["fr_france_travail_offres"]),
    early=ScoreLineOut(verdict="yes", evidence="Job ads are live now.", fact_refs=[],
                       dataset_ids=["fr_france_travail_offres"]),
    gap_evidence=ScoreLineOut(verdict="unclear",
                              evidence="An ad without a range is not proof, because pay can be given before the interview.",
                              fact_refs=["f3"], dataset_ids=["fr_france_travail_offres"]),
    crowding=ScoreLineOut(verdict="unclear", evidence="Pay transparency tools already pitch this rule.",
                          fact_refs=[], dataset_ids=[]),
    list_recipes=[RecipeOut(dataset_id="fr_france_travail_offres", filter="NAF 56, companies with 10-249 staff",
                            gap_evidence="live ads with no salary field", metric="live ads without a pay range",
                            signal_strength="weak",
                            caveat="Employers can also give pay information before the interview."),
                  RecipeOut(dataset_id="made_up_dataset", filter="all employers", gap_evidence="no range",
                            metric="count of ads", signal_strength="weak", caveat=None)],
)


def build(cfg, datasets, rewrites):
    llm = StubLLM(rewrites)
    asm = Assembler(llm, cfg, datasets, GOLDEN_TODAY)
    doc = load_eu(EU_RELEVANT)
    stats = Stats()
    facts = asm.facts(doc, READ.facts, stats)
    return asm.build(doc, READ, facts, SCORE, stats), stats, llm


def test_assembly_rules(cfg, datasets):
    entry, stats, llm = build(cfg, datasets, {
        "what_changed_2": "EU countries had to apply the rules by 1 January 2025.",     # still unbacked
        "who": ("The rule covers Ledgerly's 10-249 staff segment in France and Spain.", ["f3"]),   # fixed
    })
    # f2's quote is not in the Directive: dropped, never softened.
    assert [f.id for f in entry.facts] == ["f1", "f3"]
    assert stats.facts_dropped == 1
    # One rewrite per failing field, no more.
    assert sorted(k for _, k in llm.calls) == ["eu:32023L0970__what_changed_2", "eu:32023L0970__who"]
    assert entry.what_changed[1].text == NOT_GENERATED and "what_changed_2" in entry.not_generated
    assert entry.who.text.startswith("The rule covers")
    # Dates and deadlines come from validated facts.
    assert [(d.label, d.date.isoformat()) for d in entry.when.deadlines] == [("Transposition deadline", "2026-06-07")]
    assert entry.when.next_deadline is None                    # 7 June 2026 is before the run date
    # Scorecard points are computed in code: 2 + 2 + 2 + 2x1 + 1.
    assert entry.scorecard.gap_evidence.verdict == "unclear"
    assert entry.scorecard.points == 9 and entry.scorecard.max_points == 12
    # Catalogue datasets are verified; anything else is labelled.
    assert [(r.dataset_id, r.dataset_verified) for r in entry.list_recipes] == [
        ("fr_france_travail_offres", True), ("made_up_dataset", False)]
    assert entry.list_recipes[0].signal_strength == "weak" and entry.list_recipes[0].caveat


def test_no_surviving_fact_means_no_entry(cfg, datasets):
    llm = StubLLM({})
    asm = Assembler(llm, cfg, datasets, GOLDEN_TODAY)
    doc = load_eu(EU_RELEVANT)
    stats = Stats()
    bad = READ.model_copy(update={"facts": [READ.facts[1]]})
    facts = asm.facts(doc, bad.facts, stats)
    assert facts == {} and asm.build(doc, bad, facts, None, stats) is None
