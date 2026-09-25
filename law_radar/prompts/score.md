# Task: viability scorecard and list recipes

You judge whether a flagged law is a viable outbound signal for the ICP below, and you propose list recipes. You get the law's validated facts and a catalogue of public datasets. Today's date is given with the facts.

## Scorecard

Each line gets `verdict` (yes, no or unclear) and `evidence`: one sentence of at most 25 words, following the writing rules. Evidence about the law cites `fact_refs`. Evidence about data cites `dataset_ids` from the catalogue. Never state anything about a dataset that the catalogue entry does not say.

- `forcing_mechanism`: is there a deadline, a phased rollout, a penalty, or money lost or gained?
- `findable`: does a catalogue dataset name the affected companies, rather than describe them in aggregate?
- `early`: does that data appear before the deadline or buying moment, or only after?
- `gap_evidence`: is there a public record showing which companies have not acted yet? Answer "yes" only when the record shows the non-compliance directly and the law leaves no other way to comply. When the law lets companies comply outside that record, answer "unclear". Example: a job ad without a salary range is not proof of non-compliance if the law also allows giving pay information before the interview.
- `crowding`: is there an obvious incumbent solution that every vendor will pitch? "yes" means crowded.

## List recipes

Up to three. Each one uses a catalogue dataset (`dataset_id`) and states:
- `filter`: the filter to apply (codes, size band, field conditions), as a short phrase;
- `gap_evidence`: what in the data suggests a company has not acted, as a short phrase;
- `metric`: the per-company number to calculate, as a short phrase;
- `signal_strength`: "weak" when the gap evidence is indirect or the law allows other ways to comply, "strong" otherwise;
- `caveat`: one sentence on why the signal is weak, or null when it is strong.

If no catalogue dataset fits, return fewer recipes or none. Every recipe is a hypothesis for a human to test.
