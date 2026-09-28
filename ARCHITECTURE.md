# Architecture and Overview

## System flow

```text
Sentence or CSV row
        |
        v
  run_model.py ----> models.json ----> models/ct2 + tokenizers/
        |                                  |
        +---------- CTranslate2 CPU ------+
                         |
                         v
                 corrected text / CSV

Optional route:
Sentence --> LanguageTool --> classifier --> auto-apply / suggest / Qwen
                                      \                 |
                                       +--> validator --+
                                                    |
                                      accepted correction or original text
```

## Components

- `run_model.py`: primary CLI; loads the registry, tokenizer, and CTranslate2 `Translator` or `Generator`.
- `models.json`: model paths, architecture, prompts, length limits, and beam sizes.
- `grammar/`: LanguageTool client, finding classifier, Qwen corrector, edit extraction, routing, and safety validation.
- `run_hybrid.py`: CLI for the guarded hybrid router.
- `scripts/benchmarks/`: CSV benchmark, Ollama benchmark, hybrid evaluation, and output comparison utilities.
- `tests/`: unit tests for routing, classification, validation, and edit extraction.
- `scripts/model_setup/`: tokenizer/model preparation helpers.

## Model inventory

| Registry name | Runtime | Model path | Tokenizer path | Key setting |
| --- | --- | --- | --- | --- |
| `unbabel` | Translator | `models/ct2/unbabel-gec-t5-small-ct2-int8` | `tokenizers/unbabel-gec-t5-small-tokenizer` | Prefix `gec: `, beam 5 |
| `vennify` | Translator | `models/ct2/vennify-t5-grammar-ct2-int8` | `tokenizers/vennify-t5-tokenizer` | Prefix `grammar: `, beam 5 |
| `prithivida` | Translator | `models/ct2/prithivida-grammar-ct2-int8` | `tokenizers/prithivida-grammar-tokenizer` | Beam 5 |
| `floyd93` | Translator | `models/ct2/floyd93-grammar-correction-ct2-int8` | `tokenizers/floyd93-grammar-correction-tokenizer` | Beam 5 |
| `flan-t5` | Translator | `models/ct2/google-flan-t5-base-ct2-int8` | `tokenizers/google-flan-t5-base-tokenizer` | Instruction prompt, beam 5 |
| `qwen` | Generator | `models/ct2/qwen2.5-1.5b-instruct-ct2-int8` | `tokenizers/qwen2.5-1.5b-instruct-tokenizer` | Instruction prompt, beam 1 |
| `visheratin-mini` | Translator | `models/ct2/visheratin-t5-efficient-mini-grammar-ct2-int8` | `tokenizers/visheratin-t5-efficient-mini-grammar-tokenizer` | Beam 4 |

`models/ct2/qingy2024-grmr-2b-instruct-ct2-int8` is present but unregistered. It requires a registry entry before the main CLI can use it.

## Hybrid decision flow

1. Empty or protected input may be retained unchanged.
2. LanguageTool returns and classifies findings.
3. High-confidence findings may be auto-applied and rechecked.
4. Ambiguous findings may be routed to Qwen.
5. The validator checks edit magnitude, new errors, protected content, numbers, negation, and approximate tense.
6. Unsafe candidates are rejected and the original is returned.

The default fallback is conservative: LanguageTool failure keeps the original unless `ALLOW_MODEL_ONLY_MODE` is explicitly enabled.

## Artifact boundaries

Keep source code, tests, `models.json`, documentation, tokenizer metadata, and small input samples in Git. Keep CTranslate2 `model.bin` files, virtual environments, caches, generated reports, LanguageTool n-grams, and large downloaded checkpoints outside normal Git history. The repository `.gitignore` enforces the main exclusions.

## Adding a model

Convert the model to CTranslate2, place it under `models/ct2/`, place its tokenizer under `tokenizers/`, add a profile to `models.json`, run a sentence smoke test, and benchmark it against the input data.
