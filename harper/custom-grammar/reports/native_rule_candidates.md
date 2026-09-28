# Native Harper Rule Candidates

These cases are intentionally left out of the initial Weirpack because they need native token metadata, morphology, or sentence structure.

## 1. General subject-verb agreement

- Expected benefit: broad coverage of common agreement errors.
- Required data: lemma lookup, subject head resolution, number features.
- Difficulty: high.
- Risk: medium to high false positives.

## 2. Verb inflection after arbitrary auxiliaries

- Expected benefit: better tense handling for irregular verbs.
- Required data: verb tables and tense selection.
- Difficulty: medium.
- Risk: contextual ambiguity.

## 3. Pronoun reference resolution

- Expected benefit: repairs cases that Weir cannot safely disambiguate.
- Required data: discourse context and coreference heuristics.
- Difficulty: high.
- Risk: high.

## 4. Article selection by pronunciation

- Expected benefit: broader `a/an` coverage.
- Required data: phonetic lookup or pronunciation lexicon.
- Difficulty: medium.
- Risk: moderate.
