# Grammar Correction CT2

Local grammar correction and benchmarking with CTranslate2. It runs several CPU-friendly INT8 models through one CLI and includes an optional LanguageTool/Qwen hybrid correction pipeline.

## What it does

- Corrects one sentence or an entire CSV locally.
- Benchmarks multiple grammar-correction models.
- Applies conservative LanguageTool/Qwen corrections with validation.
- Preserves model configuration in `models.json` and keeps large model binaries outside normal Git history.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the system design and data flow.

## Registered models

| Name | Type | CTranslate2 model | Tokenizer |
| --- | --- | --- | --- |
| `unbabel` | Encoder-decoder | `models/ct2/unbabel-gec-t5-small-ct2-int8` | `tokenizers/unbabel-gec-t5-small-tokenizer` |
| `vennify` | Encoder-decoder | `models/ct2/vennify-t5-grammar-ct2-int8` | `tokenizers/vennify-t5-tokenizer` |
| `prithivida` | Encoder-decoder | `models/ct2/prithivida-grammar-ct2-int8` | `tokenizers/prithivida-grammar-tokenizer` |
| `floyd93` | Encoder-decoder | `models/ct2/floyd93-grammar-correction-ct2-int8` | `tokenizers/floyd93-grammar-correction-tokenizer` |
| `flan-t5` | Encoder-decoder | `models/ct2/google-flan-t5-base-ct2-int8` | `tokenizers/google-flan-t5-base-tokenizer` |
| `qwen` | Decoder-only | `models/ct2/qwen2.5-1.5b-instruct-ct2-int8` | `tokenizers/qwen2.5-1.5b-instruct-tokenizer` |
| `visheratin-mini` | Encoder-decoder | `models/ct2/visheratin-t5-efficient-mini-grammar-ct2-int8` | `tokenizers/visheratin-t5-efficient-mini-grammar-tokenizer` |

`models/ct2/qingy2024-grmr-2b-instruct-ct2-int8` is present but experimental and not registered in `models.json`.

## Setup

Requirements: Python 3.10+, a CPU with enough memory, and local model/tokenizer directories.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install ctranslate2 transformers sentencepiece
.venv/bin/python run_model.py --list-models
```

## Usage

```bash
.venv/bin/python run_model.py \
  --model unbabel \
  --text "He go to office every days."
```

```bash
.venv/bin/python run_model.py \
  --model vennify \
  --input-csv data/input/extracted_grammar_test_cases.csv \
  --output-csv results/vennify_results.csv
```

The default CPU compute type is `int8`. Use `--text-column`, `--limit`, `--threads`, and `--compute-type` as needed.

## Benchmarking

Benchmark utilities are under `scripts/benchmarks/`:

```bash
.venv/bin/python scripts/benchmarks/run_ct2_csv_tests.py \
  --input-csv data/input/extracted_grammar_test_cases.csv \
  --output-csv results/vennify_ct2_results.csv \
  --model-dir models/ct2/vennify-t5-grammar-ct2-int8 \
  --tokenizer-dir tokenizers/vennify-t5-tokenizer
```

`evaluate_hybrid.py` reports precision, recall, F1, accuracy, auto-apply precision, and unsafe-change rate.

## Hybrid pipeline

`grammar/` routes LanguageTool findings to auto-apply, suggestion, Qwen, or ignore actions. Candidate edits are validated for edit size, new errors, protected content, numbers, negation, and approximate tense preservation. If LanguageTool is unavailable, the default behavior keeps the original text.

Start the optional local LanguageTool server with:

```bash
LANGUAGETOOL_PORT=8082 scripts/start_languagetool.sh
```

## Repository layout

```text
run_model.py                 Primary CTranslate2 CLI
run_hybrid.py                Optional guarded LanguageTool/Qwen CLI
models.json                  Model registry
models/ct2/                  Converted CTranslate2 model artifacts
models/source/               Source or Hugging Face model artifacts
tokenizers/                  Local tokenizer directories
grammar/                     Hybrid routing and validation package
scripts/benchmarks/          Benchmark and comparison tools
scripts/model_setup/         Model/tokenizer preparation tools
scripts/start_languagetool.sh Local LanguageTool launcher
data/input/                  Input datasets and samples
results/                     Generated reports and archived outputs
tests/                       Unit tests
archive/                     Retired model-specific scripts
```

## Testing

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

## Git and model storage

`.gitignore` excludes model binaries, virtual environments, caches, dependencies, and generated results. Push the source, configuration, documentation, tests, and small inputs to GitHub. Store `model.bin` files on Hugging Face, GitHub Releases, object storage, or another artifact registry. Check upstream licenses before publishing model or tokenizer files.
