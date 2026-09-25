from law_radar.fixtures import EU_IRRELEVANT, EU_RELEVANT, load_eu
from law_radar.steps.keyword_filter import KeywordFilter, cap
from law_radar.steps.score import MAX_POINTS, points


def test_directive_passes_the_keyword_filter(cfg):
    m = KeywordFilter(cfg).match(load_eu(EU_RELEVANT, with_text=False))
    assert m.passed
    assert "directory:05202020" in m.codes
    assert "pay" in m.keywords


def test_fisheries_is_rejected_by_the_keyword_filter(cfg):
    assert not KeywordFilter(cfg).match(load_eu(EU_IRRELEVANT, with_text=False)).passed


def test_exclude_terms_lose_to_code_matches(cfg):
    doc = load_eu(EU_RELEVANT, with_text=False)
    doc = doc.model_copy(update={"title": doc.title + " and fishing"})
    assert KeywordFilter(cfg).match(doc).passed          # the directory code still matches


def test_cap_keeps_the_strongest_matches(cfg):
    kf = KeywordFilter(cfg)
    strong = kf.match(load_eu(EU_RELEVANT, with_text=False))
    weak_doc = load_eu(EU_IRRELEVANT, with_text=False).model_copy(
        update={"id": "eu:X", "title": "Regulation on vocational statistics", "classification": {}})
    weak = kf.match(weak_doc)
    kept, over = cap([weak, strong], 1)
    assert kept == [strong] and over == [weak]


def test_points():
    assert MAX_POINTS == 12
    assert points("yes", "yes", "yes", "yes", "no") == 12
    assert points("no", "no", "no", "no", "yes") == 0
    # gap evidence counts double; crowding is inverted
    assert points("yes", "yes", "yes", "unclear", "unclear") == 2 + 2 + 2 + 2 + 1


def test_keywords_apply_to_their_own_language(cfg):
    from law_radar.fixtures import FR_RELEVANT, load_fr
    decree = next(d for d in load_fr() if d.native_id == FR_RELEVANT)
    m = KeywordFilter(cfg).match(decree)
    assert m.passed and "apprenti*" in m.keywords and "apprentic*" not in m.keywords
    spanish_word_on_french_text = decree.model_copy(update={"title": "Décret relatif à la nomination des inspecteurs"})
    assert not KeywordFilter(cfg).match(spanish_word_on_french_text).passed     # "nómina*" is Spanish only


def test_french_irrelevant_text_is_rejected(cfg):
    from law_radar.fixtures import FR_IRRELEVANT, load_fr
    doc = next(d for d in load_fr() if d.native_id == FR_IRRELEVANT)
    assert not KeywordFilter(cfg).match(doc).passed


def test_spanish_codes_and_keywords(cfg):
    from law_radar.fixtures import ES_IRRELEVANT, ES_RELEVANT, load_es
    docs = {d.native_id: d for d in load_es()}
    m = KeywordFilter(cfg).match(docs[ES_RELEVANT])
    assert m.passed and "materia:6256" in m.codes
    assert not KeywordFilter(cfg).match(docs[ES_IRRELEVANT]).passed
