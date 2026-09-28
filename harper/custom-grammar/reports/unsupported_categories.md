# Unsupported Categories

The following grammar areas are not safely implemented with a narrow Weir-only approach in this repository.

- unrestricted preposition selection
- pronoun antecedent resolution
- broad clause restructuring
- semantic agreement across clauses
- tense rewriting that depends on discourse context
- unrestricted article choice for open-class nouns

Recommended fallback:

- mark these as detection-only or suggestion-only;
- push high-value cases into native Harper code only after a design review;
- keep uncertain entries out of automatic replacement rules.
