# Rule Authoring

## Supported Weir Features

The installed Harper version exposes a Weirpack loader and supports Weir files with:

- `expr main ...`
- `let message "..." `
- `let description "..." `
- `let kind "..." `
- `let becomes "..."` or an array of replacements when the pattern has alternatives
- `let strategy "Exact"` or `let strategy "MatchCase"`
- `let scope "Chunk"` or `let scope "Sentence"`
- `test "input" "expected"`
- `allows "input"`

## Naming Conventions

- Use stable IDs with the `CUSTOM_` prefix.
- Keep one public rule per `.weir` file.
- Match filenames to rule IDs when possible.
- Use short, direct titles.

## Confidence Levels

- `high`: deterministic local pattern, safe automatic replacement.
- `medium`: narrow context but still worth suggestion-only review.
- `low`: unsupported in Weir, should stay out of auto-apply.

## Auto-Apply Policy

- `auto_apply`: deterministic correction with no known harmful validation change.
- `suggestion_only`: safe to detect, but not safe to change automatically.
- `detection_only`: record only, do not apply.

## Test Expectations

- At least five positive tests per rule.
- At least ten negative or `allows` tests per rule.
- Include punctuation and capitalization boundaries when relevant.
- Include nearby valid constructions and narrow exceptions.
- Do not reuse copied examples from the reference PDF.

## Example

```weir
expr main (a hour)

let message "Use `an` before this sound."
let description "Corrects the article in a narrow pronunciation-based case."
let kind "Grammar"
let becomes "an hour"
let strategy "Exact"

test "It was a hour late." "It was an hour late."
allows "It was an honest mistake."
```
