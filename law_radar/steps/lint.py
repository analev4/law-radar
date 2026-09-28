"""Writing linter for every model-written sentence.

Returns a list of human-readable errors. An empty list means the text passes.
The errors are fed back to the model once; a second failure drops the field.
"""
from __future__ import annotations

import re
from typing import List, Optional

MAX_WORDS = 25

# Whole-word, case-insensitive. A trailing \w* lets one entry cover inflections.
BANNED_PATTERNS = {
    "landscape": r"landscapes?",
    "navigate": r"navigat\w*",
    "crucial": r"crucial(?:ly)?",
    "significant(ly)": r"significant(?:ly)?",
    "robust": r"robust(?:ly|ness)?",
    "leverage": r"leverag\w*",
    "streamline": r"streamlin\w*",
    "game-changer": r"game[- ]chang\w*",
    "paradigm": r"paradigm\w*",
    "evolving": r"evolving",
    "ever-changing": r"ever[- ]changing",
    "in today's": r"in today['’]s",
    "it is important to note": r"it is important to note",
    "stakeholders": r"stakeholders?",
    "holistic": r"holistic(?:ally)?",
    "unlock": r"unlock\w*",
    "seamless": r"seamless(?:ly)?",
    "cutting-edge": r"cutting[- ]edge",
    "delve": r"delv\w*",
    "key takeaway": r"key takeaways?",
    "bottom line": r"bottom line",
}

# Advice and hedging. The tool says what the law does, never what to do.
ADVICE_PATTERNS = {
    "should": r"should",
    "we recommend": r"we recommend",
    "it is advisable": r"it is advisable",
    "is recommended": r"(?:is|are) recommended",
    "potentially": r"potentially",
    "arguably": r"arguably",
    "it seems": r"it seems",
    "appears to": r"appears? to",
}

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U0001F900-\U0001F9FF⭐⭕⌚-⏿]"
)

# Abbreviations that end in a full stop but don't end a sentence.
ABBREVIATIONS = ["Art", "Arts", "No", "Nos", "e.g", "i.e", "cf", "para", "p", "n°", "St", "vs", "approx", "Reg", "Dir"]
# Also a single capital letter, as in French code articles ("Article L. 6243-1") or initials.
_ABBR_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in ABBREVIATIONS) + r"|[A-Z])\.(?=\s)")
_PLACEHOLDER = "\u0000"


def split_sentences(text: str) -> List[str]:
    """Split on . ! ? followed by whitespace, ignoring common abbreviations and decimals."""
    protected = _ABBR_RE.sub(lambda m: m.group(1) + _PLACEHOLDER, text.strip())
    parts = re.split(r"(?<=[.!?])\s+", protected)
    return [p.replace(_PLACEHOLDER, ".").strip() for p in parts if p.strip()]


def count_words(sentence: str) -> int:
    return len(re.findall(r"[^\s]+", sentence))


def lint(text: str, expected_sentences: Optional[int] = None) -> List[str]:
    errors: List[str] = []
    if not text or not text.strip():
        return ["empty text"]

    lowered = text.lower()
    for label, pattern in BANNED_PATTERNS.items():
        if re.search(r"(?<![\w-])" + pattern + r"(?![\w-])", lowered):
            errors.append(f"banned term: {label}")
    for label, pattern in ADVICE_PATTERNS.items():
        if re.search(r"(?<![\w-])" + pattern + r"(?![\w-])", lowered):
            errors.append(f"advice or hedging: {label}")

    if "—" in text:
        errors.append("em dash")
    if re.search(r"\s–\s", text):
        errors.append("spaced en dash used as a dash")
    if "!" in text:
        errors.append("exclamation mark")
    if "?" in text:
        errors.append("question")
    if EMOJI_RE.search(text):
        errors.append("emoji")

    sentences = split_sentences(text)
    for s in sentences:
        n = count_words(s)
        if n > MAX_WORDS:
            errors.append(f"sentence has {n} words (max {MAX_WORDS}): {s[:60]}...")
    if expected_sentences is not None and len(sentences) != expected_sentences:
        errors.append(f"expected {expected_sentences} sentence(s), got {len(sentences)}")
    return errors
