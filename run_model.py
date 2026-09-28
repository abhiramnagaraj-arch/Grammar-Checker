#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import ctranslate2
from transformers import AutoTokenizer


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "models.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing configuration file: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def validate_model_directory(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Directory does not exist: {path}")
    if not ctranslate2.contains_model(str(path)):
        raise ValueError(f"Not a valid CTranslate2 model directory: {path}")


class GrammarModel:
    def __init__(
        self,
        model_name: str,
        config: dict[str, Any],
        threads: int,
        compute_type: str,
    ) -> None:
        self.name = model_name
        self.config = config
        self.architecture = config["architecture"]
        self.model_path = resolve_path(config["model_path"])
        self.tokenizer_path = resolve_path(config["tokenizer_path"])

        validate_model_directory(self.model_path)
        if not self.tokenizer_path.exists():
            raise FileNotFoundError(
                f"Tokenizer directory does not exist: {self.tokenizer_path}"
            )

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.tokenizer_path),
            local_files_only=True,
            use_fast=True,
        )

        runtime_kwargs = {
            "device": "cpu",
            "compute_type": compute_type,
            "inter_threads": 1,
            "intra_threads": threads,
        }

        if self.architecture == "encoder-decoder":
            self.runtime = ctranslate2.Translator(
                str(self.model_path),
                **runtime_kwargs,
            )
        elif self.architecture == "decoder-only":
            self.runtime = ctranslate2.Generator(
                str(self.model_path),
                **runtime_kwargs,
            )
        else:
            raise ValueError(
                "architecture must be 'encoder-decoder' or 'decoder-only'"
            )

    def _tokenize(self, text: str, max_length: int) -> list[str]:
        token_ids = self.tokenizer.encode(
            text,
            add_special_tokens=True,
            truncation=True,
            max_length=max_length,
        )
        return self.tokenizer.convert_ids_to_tokens(token_ids)

    def _decode(self, tokens: list[str]) -> str:
        token_ids = self.tokenizer.convert_tokens_to_ids(tokens)
        return self.tokenizer.decode(
            token_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()

    def _build_decoder_prompt(self, text: str) -> str:
        prompt_template = self.config.get("prompt_template", "{text}")
        prompt = prompt_template.format(text=text)

        if getattr(self.tokenizer, "chat_template", None):
            messages = []
            system_prompt = self.config.get("system_prompt")
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            return self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

        return prompt

    def correct(self, text: str) -> tuple[str, float]:
        clean_text = text.strip()
        if not clean_text:
            return "", 0.0

        started = time.perf_counter()

        if self.architecture == "encoder-decoder":
            prefix = self.config.get("prefix", "")
            prompt = f"{prefix}{clean_text}"
            input_tokens = self._tokenize(
                prompt,
                self.config.get("max_input_length", 128),
            )
            results = self.runtime.translate_batch(
                [input_tokens],
                beam_size=self.config.get("beam_size", 5),
                max_input_length=self.config.get("max_input_length", 128),
                max_decoding_length=self.config.get("max_output_length", 128),
                repetition_penalty=1.05,
            )
            output_tokens = results[0].hypotheses[0]
            corrected = self._decode(output_tokens)
        else:
            prompt = self._build_decoder_prompt(clean_text)
            prompt_tokens = self._tokenize(
                prompt,
                self.config.get("max_input_length", 256),
            )

            end_token = self.tokenizer.eos_token if self.tokenizer.eos_token else None

            results = self.runtime.generate_batch(
                [prompt_tokens],
                beam_size=self.config.get("beam_size", 1),
                max_length=self.config.get("max_output_length", 128),
                include_prompt_in_result=False,
                repetition_penalty=1.05,
                no_repeat_ngram_size=4,
                end_token=end_token,
            )
            output_tokens = results[0].sequences_ids[0]
            corrected = self.tokenizer.decode(
                output_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ).strip()

            for prefix in self.config.get("postprocess_prefixes", []):
                if corrected.startswith(prefix):
                    corrected = corrected[len(prefix) :].strip()
                    break

        elapsed = time.perf_counter() - started
        return corrected, elapsed


def run_interactive(model: GrammarModel) -> None:
    print("\nInteractive mode")
    print("Enter 'quit' or 'exit' to stop.")

    while True:
        try:
            sentence = input("\nSentence: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if sentence.lower() in {"quit", "exit"}:
            return
        if not sentence:
            continue

        corrected, elapsed = model.correct(sentence)
        print(f"Original  : {sentence}")
        print(f"Corrected : {corrected}")
        print(f"Time      : {elapsed:.3f} seconds")


def run_csv(
    model: GrammarModel,
    input_path: Path,
    output_path: Path,
    text_column: str,
    limit: int | None,
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"CSV not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if not reader.fieldnames:
            raise ValueError("The CSV has no header.")
        if text_column not in reader.fieldnames:
            raise ValueError(
                f"Column '{text_column}' not found. Available columns: {reader.fieldnames}"
            )

        rows = list(reader)
        if limit is not None:
            rows = rows[:limit]

        fieldnames = list(reader.fieldnames)
        for extra_column in ["model", "corrected_text", "inference_seconds"]:
            if extra_column not in fieldnames:
                fieldnames.append(extra_column)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()

        for index, row in enumerate(rows, start=1):
            original = (row.get(text_column) or "").strip()
            try:
                corrected, elapsed = model.correct(original)
                row["corrected_text"] = corrected
                row["inference_seconds"] = f"{elapsed:.4f}"
            except Exception as error:
                row["corrected_text"] = f"ERROR: {error}"
                row["inference_seconds"] = ""

            row["model"] = model.name
            writer.writerow(row)
            print(f"Processed row {index}")

    print(f"\nResults saved to: {output_path}")


def build_parser(configurations: dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run any local CTranslate2 grammar-correction model."
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List configured models and exit.",
    )
    parser.add_argument(
        "--model",
        choices=sorted(configurations.keys()),
        help="Model profile name from models.json.",
    )
    parser.add_argument(
        "--text",
        help="Correct one sentence from the terminal.",
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="Run all rows from a CSV file.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Write CSV output here. Defaults to results/<model>_results.csv.",
    )
    parser.add_argument(
        "--text-column",
        default="input",
        help="CSV column containing the sentence to correct. Default: input.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N CSV rows.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        help="CPU inference threads. Default: 8.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="CTranslate2 compute type. Default: int8.",
    )
    return parser


def main() -> None:
    configurations = load_config()
    parser = build_parser(configurations)
    args = parser.parse_args()

    if args.list_models:
        print("Configured models:")
        for name, profile in configurations.items():
            print(f"  {name:12} {profile['architecture']}")
        return

    if not args.model:
        parser.error("--model is required unless --list-models is used.")

    try:
        model = GrammarModel(
            model_name=args.model,
            config=configurations[args.model],
            threads=args.threads,
            compute_type=args.compute_type,
        )

        print("CTranslate2 version:", ctranslate2.__version__)
        print("Tokenizer:", type(model.tokenizer).__name__)
        print("Model:", model.name)
        print("Architecture:", model.architecture)
        print("Model path:", model.model_path)
        print("Tokenizer path:", model.tokenizer_path)

        if args.input_csv:
            output_path = args.output_csv
            if output_path is None:
                output_path = BASE_DIR / "results" / f"{args.model}_results.csv"
            run_csv(
                model=model,
                input_path=args.input_csv,
                output_path=output_path,
                text_column=args.text_column,
                limit=args.limit,
            )
            return

        if args.text:
            corrected, elapsed = model.correct(args.text)
            print(f"\nOriginal  : {args.text}")
            print(f"Corrected : {corrected}")
            print(f"Time      : {elapsed:.3f} seconds")
            return

        run_interactive(model)

    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
