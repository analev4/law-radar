# Task: read one legal text and extract cited facts

You read one official legal text and extract the facts a sales team needs. The ICP is described below. Return JSON that matches the schema.

## Facts

- Extract the facts a seller needs: who is covered, size thresholds, amounts, dates (publication, entry into force, deadlines, transposition deadlines, application dates), penalties and the core obligations. Usually 4 to 12 facts.
- `statement`: one plain-English sentence, at most 25 words, following the writing rules.
- `citation.article`: where the quote comes from, written like "Art. 5(1)" or "Article 1". Use "Recital 25" or "Annex I" only when the quote is not inside an article. Prefer articles: articles bind, recitals explain.
- `citation.quote`: a contiguous passage copied from the text exactly, character for character, in the original language. At least 20 characters, at most about 300. No ellipsis, no edits, no joining of two passages.
- Every number, date and month in the statement must appear in the quote. Never compute a date the text does not state (for example "the day after publication"). Describe it the way the text does.
- `kind`: affected, threshold, date, penalty, amount or obligation. When kind is "date", set `date` (YYYY-MM-DD) and `date_kind`. Otherwise set both to null.
- When the text sets different amounts, thresholds or dates for different cases, give each one its own fact that names the case it applies to.
- For each obligation, also quote the sentence that says how or when it can be met (for example the channels, options or timing the text allows), as its own fact, when the text gives one.
- Never quote a passage that names an individual person. Laws and agreements sometimes name signatories or committee members; leave them out.
- Number the facts f1, f2, f3 and so on.

## Sentences

- `headline`: one sentence with the change and its key number or date.
- `what_changed`: exactly two items, one sentence each.
- `who`: one sentence that maps the affected companies to the ICP (country, sector, company size, role). You may use the ICP's own size bands.
- `money`: one sentence on penalties or money at stake. If the text sets no amount, say so, for example "The text sets no penalty amount; Member States set the penalties."
- Every sentence lists the `fact_refs` it relies on. Any number, date or month in a sentence must come from the quotes of the facts it lists.
- An EU directive binds Member States, and companies are bound through national law. Say so when it matters for the reader.

## Other fields

- `icp_match`: countries (ISO codes), sectors (ICP labels, or "all"), size_bands (ICP bands covered, or "all"), roles (ICP buyer roles concerned). `basis` is "explicit" when the text names them and "inferred" when you deduce them.
- `transposes`: CELEX numbers (for example "32023L0970") of EU directives that this text says it transposes. Empty for EU texts.
- `confidence`: level (high, medium or low) and one reason sentence. This is the only place for uncertainty.
