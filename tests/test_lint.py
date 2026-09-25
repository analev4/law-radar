import pytest

from law_radar.steps.lint import lint, split_sentences

BAD = [
    ("This significant directive introduces crucial new transparency requirements that organisations "
     "will need to navigate in the evolving pay landscape.", ["significant", "crucial", "navigate", "evolving", "landscape"]),
    ("Employers should consider publishing pay ranges.", ["should"]),
    ("The rules change everything!", ["exclamation mark"]),
    ("Are you ready for the new rules?", ["question"]),
    ("Employers must publish ranges — from June.", ["em dash"]),
    ("Employers must publish ranges – from June.", ["spaced en dash"]),
    ("Pay transparency is here \U0001F680", ["emoji"]),
    ("It is important to note that employers must report.", ["it is important to note"]),
    ("HR teams can leverage the new rules to streamline hiring.", ["leverage", "streamline"]),
    ("This is a game-changer for stakeholders.", ["game-changer", "stakeholders"]),
    ("Employers will potentially face audits.", ["potentially"]),
]


@pytest.mark.parametrize("text,expected", BAD)
def test_bad_sentences_fail(text, expected):
    errors = " | ".join(lint(text))
    for label in expected:
        assert label in errors, f"{label!r} not flagged in {text!r}: {errors}"


GOOD = [
    "EU countries must apply the pay transparency rules by 7 June 2026 (Art. 34).",
    "Job applicants get the right to the starting pay or its range, in the ad or before the interview (Art. 5).",
    "From 8 March 2026, employers with fewer than 250 staff get up to €4,500 per apprentice.",
    "The text sets no penalty amount.",
    "Employers with 100 to 249 workers report every three years (Art. 9).",
    "Companies with 10–249 staff in hospitality are covered.",
]


@pytest.mark.parametrize("text", GOOD)
def test_good_sentences_pass(text):
    assert lint(text) == []


def test_sentence_length_limit():
    long = " ".join(["word"] * 26) + "."
    assert any("26 words" in e for e in lint(long))
    assert lint(" ".join(["word"] * 25) + ".") == []


def test_sentence_count():
    two = "EU countries must apply the rules by 7 June 2026 (Art. 34). Applicants get the pay range (Art. 5)."
    assert lint(two, expected_sentences=2) == []
    assert any("expected 1 sentence" in e for e in lint(two, expected_sentences=1))


def test_abbreviations_do_not_split_sentences():
    assert split_sentences("Employers must report under Art. 9 of the Directive. They must also publish.") == [
        "Employers must report under Art. 9 of the Directive.", "They must also publish."]


def test_banned_words_match_whole_words_only():
    assert lint("The Leverhulme centre published the text.") == []       # contains "leve" but not "leverage"
    assert lint("Employers must unlock nothing.") != []
