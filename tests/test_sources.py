"""Source parsers run on saved publisher payloads. No network."""
import datetime as dt

from law_radar.fixtures import EU_IRRELEVANT, EU_RELEVANT, load_eu
from law_radar.sources.eu_cellar import parse_list


def test_eu_directive_metadata():
    doc = load_eu(EU_RELEVANT, with_text=False)
    assert doc.id == "eu:32023L0970"
    assert doc.doc_type == "Directive"
    assert doc.published == dt.date(2023, 5, 17)
    assert doc.entry_into_force == dt.date(2023, 6, 6)
    assert doc.title.startswith("Directive (EU) 2023/970")
    assert "05202020" in doc.classification["directory"]
    assert "equal pay" in doc.classification["eurovoc_labels"]
    assert doc.url == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023L0970"


def test_eu_text_is_split_into_articles():
    doc = load_eu(EU_RELEVANT)
    assert len(doc.articles) == 37
    art5 = next(a for a in doc.articles if a.num == "5")
    assert art5.heading == "Pay transparency prior to employment"
    assert "such as in a published job vacancy notice, prior to the job interview or otherwise" in \
        " ".join(art5.text.split())
    art34 = next(a for a in doc.articles if a.num == "34")
    assert "by 7 June 2026" in art34.text


def test_eu_fisheries_metadata():
    doc = load_eu(EU_IRRELEVANT)
    assert doc.doc_type == "Regulation"
    assert doc.published == dt.date(2026, 8, 11)
    assert "sea fishing" in doc.classification["eurovoc_labels"]
    assert doc.articles


def test_corrigenda_are_skipped_by_default():
    rows = [
        {"work": "w1", "celex": "32026R2105", "pub": "2026-09-21", "type": "R"},
        {"work": "w2", "celex": "32026D1149R(01)", "pub": "2026-09-21", "type": "D"},
    ]
    assert [d.native_id for _, d in parse_list(rows, include_corrigenda=False)] == ["32026R2105"]
    assert len(parse_list(rows, include_corrigenda=True)) == 2


# ---------------------------------------------------------------------------
# France (a subset of the real DILA dump JORF_20260307-002619.tar.gz)
# ---------------------------------------------------------------------------

def test_fr_apprentice_decree_is_parsed():
    from law_radar.fixtures import FR_RELEVANT, load_fr
    doc = next(d for d in load_fr() if d.native_id == FR_RELEVANT)
    assert doc.id == "fr:JORFTEXT000053634597" and doc.doc_type == "Décret" and doc.language == "fr"
    assert doc.published == dt.date(2026, 3, 7)
    assert doc.title.startswith("Décret n° 2026-168 du 6 mars 2026")
    assert doc.url == "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000053634597"
    assert doc.text_url.endswith("JORF_20260307-002619.tar.gz#JORFTEXT000053634597")
    assert "Ministère du travail et des solidarités" in doc.classification["headings"]
    assert [a.num for a in doc.articles] == ["1", "2", "3"]
    art1 = doc.articles[0].text
    for amount in ["4 500 euros maximum", "2 000 euros maximum", "1 500 euros maximum", "750 euros maximum",
                   "6 000 euros maximum"]:
        assert amount in art1
    assert "Publics concernés : employeurs d'apprentis" in doc.text          # the notice is kept


def test_fr_nominative_sections_are_never_read():
    from law_radar.fixtures import FR_EXCLUDED, load_fr
    assert FR_EXCLUDED not in {d.native_id for d in load_fr()}


def test_fr_archive_window():
    from law_radar.sources.fr_dila import archives_for_window, list_archives
    html = ('<a href="JORF_20260306-214123.tar.gz">x</a><a href="JORF_20260307-002619.tar.gz">x</a>'
            '<a href="JORF_20260309-002000.tar.gz">x</a><a href="JORF_20260312-002000.tar.gz">x</a>')
    names = archives_for_window(list_archives(html), dt.date(2026, 3, 7), dt.date(2026, 3, 8))
    assert names == ["JORF_20260306-214123.tar.gz", "JORF_20260307-002619.tar.gz", "JORF_20260309-002000.tar.gz"]


def test_transposition_detection():
    from law_radar.sources.transpose import transposed_directives
    assert transposed_directives("Le présent décret transpose la directive (UE) 2023/970 du 10 mai 2023.") == ["32023L0970"]
    assert transposed_directives("dans le cadre de la transposition de la directive (UE) 2019/882 du Parlement") == ["32019L0882"]
    assert transposed_directives("La presente ley incorpora al ordenamiento la Directiva 2006/54/CE.") == ["32006L0054"]
    assert transposed_directives("Vu la directive (UE) 2023/970 ;") == []                  # a visa is not a transposition
    assert transposed_directives("leur transposition didactique : quarante minutes") == []


# ---------------------------------------------------------------------------
# Spain (the real BOE of 19 February 2026, trimmed)
# ---------------------------------------------------------------------------

def test_es_summary_filtering():
    import json
    from law_radar.config import ESSource
    from law_radar.fixtures import ES_SUMARIO, FIXTURES
    from law_radar.sources.es_boe import sumario_items, wanted
    cfg = ESSource()
    items = sumario_items(json.loads((FIXTURES / "es" / ES_SUMARIO).read_text()))
    kept = {i["id"] for i in items if wanted(i, cfg.sections, cfg.section3_epigraphs)}
    assert kept == {"BOE-A-2026-3814", "BOE-A-2026-3815", "BOE-A-2026-3870"}
    # Section 2 (appointments) is never read, even if the config asks for it.
    appointment = next(i for i in items if i["section"] == "2A")
    assert not wanted(appointment, ["1", "2A", "2B"], [])
    # Section 3 only under the listed epigraphs: the collective agreement yes, the fishing order no.
    assert not wanted(next(i for i in items if i["id"] == "BOE-A-2026-3874"), cfg.sections, cfg.section3_epigraphs)


def test_es_minimum_wage_decree_is_parsed():
    from law_radar.fixtures import ES_RELEVANT, load_es
    doc = next(d for d in load_es() if d.native_id == ES_RELEVANT)
    assert doc.id == "es:BOE-A-2026-3815" and doc.doc_type == "Real Decreto" and doc.language == "es"
    assert doc.published == dt.date(2026, 2, 19) and doc.entry_into_force == dt.date(2026, 2, 20)
    assert doc.classification["materias"] == ["6256"]
    assert doc.url == "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-3815"
    assert [a.num for a in doc.articles] == ["1", "2", "3", "4"]
    assert "40,70 euros/día o 1 221 euros/mes" in doc.articles[0].text
    assert "Disposición final tercera" in doc.text and "Disposición final tercera" not in doc.articles[-1].text
