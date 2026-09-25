import datetime as dt

from law_radar.fixtures import EU_RELEVANT, load_eu
from law_radar.models import Article, CitationOut, Document, FactOut
from law_radar.steps.validate import check_fact, check_sentence, parse_article_ref, validate_facts


def fact(fid="f1", statement="EU countries must apply the rules by 7 June 2026.", article="Art. 34(1)",
         quote="Member States shall bring into force the laws, regulations and administrative provisions "
               "necessary to comply with this Directive by 7 June 2026.",
         kind="date", date="2026-06-07", date_kind="transposition_deadline"):
    return FactOut(id=fid, kind=kind, statement=statement, date=date, date_kind=date_kind,
                   citation=CitationOut(article=article, quote=quote))


def directive():
    return load_eu(EU_RELEVANT)


def test_valid_fact_passes_and_checks_the_article():
    f, reason = check_fact(directive(), fact())
    assert reason is None
    assert f.citation.article_checked is True
    assert f.date == dt.date(2026, 6, 7)
    assert f.citation.url.endswith("CELEX:32023L0970")


def test_quote_not_in_document_is_dropped():
    bad = fact(quote="Member States shall bring into force the pay transparency rules by 1 January 2025.",
               statement="EU countries must apply the rules by 1 January 2025.", date="2025-01-01")
    kept, dropped = validate_facts(directive(), [fact(), bad.model_copy(update={"id": "f2"})])
    assert [f.id for f in kept] == ["f1"]
    assert dropped == [("f2", "quote not found in the fetched text")]


def test_quote_in_wrong_article_is_dropped():
    f, reason = check_fact(directive(), fact(article="Art. 5"))
    assert f is None and "not in cited article" in reason


def test_unknown_article_is_dropped():
    f, reason = check_fact(directive(), fact(article="Article 99"))
    assert f is None and "not found" in reason


def test_number_not_in_quote_is_dropped():
    f, reason = check_fact(directive(), fact(statement="EU countries must apply the rules by 7 June 2027."))
    assert f is None and "2027" in reason


def test_month_not_in_quote_is_dropped():
    f, reason = check_fact(directive(), fact(statement="EU countries must apply the rules by 7 July 2026."))
    assert f is None and "months" in reason


def test_date_value_must_match_quote():
    f, reason = check_fact(directive(), fact(date="2026-06-08"))
    assert f is None and "date" in reason


def test_short_quote_is_dropped():
    f, reason = check_fact(directive(), fact(quote="7 June 2026", statement="The deadline is 7 June 2026."))
    assert f is None and "shorter" in reason


def test_whitespace_and_nbsp_are_normalised():
    doc = Document(id="fr:X", source="fr", market="FR", native_id="X", title="t", language="fr",
                   doc_type="DECRET", published=dt.date(2026, 3, 7), url="u", text_url="u",
                   text="Le montant de l'aide est de 4 500 euros maximum pour les contrats mentionnés au 1°",
                   articles=[Article(num="1", text="Le montant de l'aide est de 4 500 euros maximum pour "
                                                   "les contrats mentionnés au 1°")])
    f, reason = check_fact(doc, fact(statement="Employers get up to €4,500 per contract.", article="Article 1",
                                     quote="Le montant de l'aide est de 4 500 euros maximum",
                                     kind="amount", date=None, date_kind=None))
    assert reason is None, reason


def test_number_words_in_french_quotes():
    doc = Document(id="fr:Y", source="fr", market="FR", native_id="Y", title="t", language="fr",
                   doc_type="DECRET", published=dt.date(2026, 3, 7), url="u", text_url="u",
                   text="Pour les contrats conclus par une entreprise de moins de deux cent cinquante salariés.")
    f, reason = check_fact(doc, fact(statement="The aid covers companies with fewer than 250 staff.",
                                     article="Article 1", kind="threshold", date=None, date_kind=None,
                                     quote="une entreprise de moins de deux cent cinquante salariés"))
    assert reason is None, reason
    assert f.citation.article_checked is False      # no article split: checked against the whole text


def test_article_refs():
    assert parse_article_ref("Art. 34(1)") == ("article", "34")
    assert parse_article_ref("Article 1er") == ("article", "1")
    assert parse_article_ref("Artículo único") == ("article", "unique")
    assert parse_article_ref("Recital 25") == ("recital", None)
    assert parse_article_ref("Annex I") == ("annex", None)


def test_sentence_numbers_must_come_from_cited_facts():
    f, _ = check_fact(directive(), fact())
    facts = {"f1": f}
    assert check_sentence("EU countries must apply the rules by 7 June 2026 (Art. 34).", ["f1"], facts) == []
    assert check_sentence("EU countries must apply the rules by 7 June 2026.", ["f9"], facts)
    errors = check_sentence("Employers with 50 staff must comply by 7 June 2026.", ["f1"], facts)
    assert any("50" in e for e in errors)
    assert check_sentence("Employers with 50 staff must comply by 7 June 2026.", ["f1"], facts, {"50"}) == []


def test_article_lists_are_not_figures():
    from law_radar.textnorm import statement_numbers
    assert statement_numbers("Fines apply (Art. 9(3), 23(2)).") == set()
    assert statement_numbers("Employers report under Articles 5, 6 and 7 by 7 June 2027.") == {"7", "2027"}
