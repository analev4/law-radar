# Task: fix one field

One field of a legal digest failed automatic checks. Rewrite it so it passes, keeping the meaning.

- Fix every error listed.
- Use only numbers, dates and months that appear in the quotes of the facts you cite.
- List in `fact_refs` the ids of the facts the text relies on. You may cite any fact given, including ones the old text did not cite.
- Follow the writing rules.

Return JSON: {"text": "...", "fact_refs": ["f1", ...]}.
