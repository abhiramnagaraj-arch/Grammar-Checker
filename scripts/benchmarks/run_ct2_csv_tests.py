#!/usr/bin/env python3
"""
Run a CSV grammar-correction benchmark with a local CTranslate2 T5 model.

Example: test the first 10 rows
--------------------------------
python run_ct2_csv_tests.py \
  --input-csv "extracted_grammar_test_cases.csv" \
  --output-csv "vennify_ct2_test10_results.csv" \
  --model-dir "./vennify-t5-grammar-ct2-int8" \
  --tokenizer-dir "./vennify-t5-tokenizer" \
  --limit 10

Example: run all rows
---------------------
python run_ct2_csv_tests.py \
  --input-csv "extracted_grammar_test_cases.csv" \
  --output-csv "vennify_ct2_all_results.csv" \
  --model-dir "./vennify-t5-grammar-ct2-int8" \
  --tokenizer-dir "./vennify-t5-tokenizer"
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import ctranslate2
from transformers import AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run grammar-correction test cases from a CSV using a local "
            "CTranslate2 INT8 T5 model."
        )
    )
    parser.add_argument(
        "--input-csv",
        required=True,
        help="Input CSV containing the test sentences.",
    )
    parser.add_argument(
        "--output-csv",
        default="vennify_ct2_results.csv",
        help="Detailed results CSV. Default: vennify_ct2_results.csv",
    )
    parser.add_argument(
        "--model-dir",
        default="./vennify-t5-grammar-ct2-int8",
        help="CTranslate2 model directory.",
    )
    parser.add_argument(
        "--tokenizer-dir",
        default="./vennify-t5-tokenizer",
        help="Local Hugging Face tokenizer directory.",
    )
    parser.add_argument(
        "--input-column",
        default=None,
        help=(
            "Input column name. Auto-detected from 'input' when omitted."
        ),
    )
    parser.add_argument(
        "--expected-column",
        default=None,
        help=(
            "Expected-answer column. Auto-detected from "
            "'expected_output' or 'Correct Sentence' when omitted."
        ),
    )
    parser.add_argument(
        "--use-case-column",
        default=None,
        help=(
            "Use-case column. Auto-detected from 'use_case' or "
            "'Use Case' when omitted."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N selected rows.",
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=1,
        help="1-based data row at which to start. Default: 1",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help=(
            "Number of examples processed in one translate_batch call. "
            "Default: 1, which gives true per-sentence latency."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=min(8, os.cpu_count() or 1),
        help="CTranslate2 intra-op CPU threads. Default: up to 8.",
    )
    parser.add_argument(
        "--inter-threads",
        type=int,
        default=1,
        help="Parallel CTranslate2 workers. Default: 1.",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="Beam-search size. Default: 5.",
    )
    parser.add_argument(
        "--max-input-length",
        type=int,
        default=512,
        help="Maximum tokenizer input length. Default: 512.",
    )
    parser.add_argument(
        "--max-decoding-length",
        type=int,
        default=128,
        help="Maximum generated length. Default: 128.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        choices=["int8", "int8_float32", "float32", "auto", "default"],
        help="CTranslate2 CPU compute type. Default: int8.",
    )
    parser.add_argument(
        "--prefix",
        default="grammar: ",
        help="Text prepended to every input. Default: 'grammar: '.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print progress after every N completed rows. Default: 10.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.start_row < 1:
        raise ValueError("--start-row must be at least 1.")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1.")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1.")
    if args.threads < 1:
        raise ValueError("--threads must be at least 1.")
    if args.inter_threads < 1:
        raise ValueError("--inter-threads must be at least 1.")
    if args.beam_size < 1:
        raise ValueError("--beam-size must be at least 1.")


def find_column(
    fieldnames: list[str],
    requested: str | None,
    candidates: Iterable[str],
    required: bool,
) -> str | None:
    """Find a CSV column while tolerating case and surrounding spaces."""
    cleaned_to_original = {
        name.strip().casefold(): name for name in fieldnames
    }

    if requested:
        key = requested.strip().casefold()
        if key not in cleaned_to_original:
            raise ValueError(
                f"Column {requested!r} was not found. "
                f"Available columns: {fieldnames}"
            )
        return cleaned_to_original[key]

    for candidate in candidates:
        key = candidate.strip().casefold()
        if key in cleaned_to_original:
            return cleaned_to_original[key]

    if required:
        raise ValueError(
            f"Could not detect a required column. "
            f"Tried {list(candidates)}. Available columns: {fieldnames}"
        )
    return None


def read_rows(
    path: Path,
    start_row: int,
    limit: int | None,
) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("The input CSV has no header row.")

        all_rows = list(reader)
        selected = all_rows[start_row - 1 :]
        if limit is not None:
            selected = selected[:limit]

        return selected, list(reader.fieldnames)


def normalize_text(text: str) -> str:
    """Normalization used for benchmark comparison, not model input."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def similarity_percent(actual: str, expected: str) -> float | None:
    if not expected:
        return None
    return round(
        SequenceMatcher(
            None,
            normalize_text(actual),
            normalize_text(expected),
        ).ratio()
        * 100,
        2,
    )


def chunks(items: list[dict[str, str]], size: int):
    for start in range(0, len(items), size):
        yield start, items[start : start + size]


def tokenize_inputs(
    rows: list[dict[str, str]],
    input_column: str,
    tokenizer,
    prefix: str,
    max_input_length: int,
) -> list[list[str]]:
    token_batches: list[list[str]] = []

    for row in rows:
        text = (row.get(input_column) or "").strip()
        prompt = f"{prefix}{text}"

        input_ids = tokenizer.encode(
            prompt,
            add_special_tokens=True,
            truncation=True,
            max_length=max_input_length,
        )
        token_batches.append(tokenizer.convert_ids_to_tokens(input_ids))

    return token_batches


def decode_result(result, tokenizer) -> str:
    output_tokens = result.hypotheses[0]
    output_ids = tokenizer.convert_tokens_to_ids(output_tokens)
    return tokenizer.decode(
        output_ids,
        skip_special_tokens=True,
    ).strip()


def make_summary_path(output_path: Path) -> Path:
    return output_path.with_name(
        f"{output_path.stem}_summary{output_path.suffix}"
    )


def write_detailed_results(
    path: Path,
    rows: list[dict[str, str]],
    original_fields: list[str],
) -> None:
    added_fields = [
        "ct2_output",
        "ct2_status",
        "ct2_batch_time_seconds",
        "ct2_avg_time_per_item_seconds",
        "ct2_exact_match",
        "ct2_normalized_match",
        "ct2_similarity_percent",
        "ct2_error",
    ]
    output_fields = list(original_fields)
    for field in added_fields:
        if field not in output_fields:
            output_fields.append(field)

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=output_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    path: Path,
    rows: list[dict[str, str]],
    use_case_column: str | None,
) -> None:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        group = (
            (row.get(use_case_column) or "").strip()
            if use_case_column
            else "ALL"
        )
        groups[group or "UNSPECIFIED"].append(row)

    summary_fields = [
        "use_case",
        "total_cases",
        "successful_cases",
        "error_cases",
        "exact_matches",
        "normalized_matches",
        "exact_match_percent",
        "normalized_match_percent",
        "average_similarity_percent",
        "total_inference_seconds",
        "average_seconds_per_case",
    ]

    summary_rows = []
    for group_name in sorted(groups):
        group_rows = groups[group_name]
        successful = [
            row for row in group_rows if row.get("ct2_status") == "success"
        ]
        exact = sum(row.get("ct2_exact_match") == "True" for row in successful)
        normalized = sum(
            row.get("ct2_normalized_match") == "True"
            for row in successful
        )
        similarities = [
            float(row["ct2_similarity_percent"])
            for row in successful
            if row.get("ct2_similarity_percent") not in (None, "")
        ]
        per_item_times = [
            float(row["ct2_avg_time_per_item_seconds"])
            for row in successful
            if row.get("ct2_avg_time_per_item_seconds") not in (None, "")
        ]

        success_count = len(successful)
        summary_rows.append(
            {
                "use_case": group_name,
                "total_cases": len(group_rows),
                "successful_cases": success_count,
                "error_cases": len(group_rows) - success_count,
                "exact_matches": exact,
                "normalized_matches": normalized,
                "exact_match_percent": (
                    round(exact / success_count * 100, 2)
                    if success_count
                    else ""
                ),
                "normalized_match_percent": (
                    round(normalized / success_count * 100, 2)
                    if success_count
                    else ""
                ),
                "average_similarity_percent": (
                    round(sum(similarities) / len(similarities), 2)
                    if similarities
                    else ""
                ),
                "total_inference_seconds": (
                    round(sum(per_item_times), 6)
                    if per_item_times
                    else ""
                ),
                "average_seconds_per_case": (
                    round(sum(per_item_times) / len(per_item_times), 6)
                    if per_item_times
                    else ""
                ),
            }
        )

    # Add an overall row.
    all_successful = [
        row for row in rows if row.get("ct2_status") == "success"
    ]
    all_exact = sum(
        row.get("ct2_exact_match") == "True" for row in all_successful
    )
    all_normalized = sum(
        row.get("ct2_normalized_match") == "True" for row in all_successful
    )
    all_similarities = [
        float(row["ct2_similarity_percent"])
        for row in all_successful
        if row.get("ct2_similarity_percent") not in (None, "")
    ]
    all_times = [
        float(row["ct2_avg_time_per_item_seconds"])
        for row in all_successful
        if row.get("ct2_avg_time_per_item_seconds") not in (None, "")
    ]
    all_count = len(all_successful)

    summary_rows.append(
        {
            "use_case": "__OVERALL__",
            "total_cases": len(rows),
            "successful_cases": all_count,
            "error_cases": len(rows) - all_count,
            "exact_matches": all_exact,
            "normalized_matches": all_normalized,
            "exact_match_percent": (
                round(all_exact / all_count * 100, 2) if all_count else ""
            ),
            "normalized_match_percent": (
                round(all_normalized / all_count * 100, 2)
                if all_count
                else ""
            ),
            "average_similarity_percent": (
                round(sum(all_similarities) / len(all_similarities), 2)
                if all_similarities
                else ""
            ),
            "total_inference_seconds": (
                round(sum(all_times), 6) if all_times else ""
            ),
            "average_seconds_per_case": (
                round(sum(all_times) / len(all_times), 6)
                if all_times
                else ""
            ),
        }
    )

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)


def main() -> int:
    args = parse_args()

    try:
        validate_args(args)

        input_path = Path(args.input_csv).expanduser().resolve()
        output_path = Path(args.output_csv).expanduser().resolve()
        model_path = Path(args.model_dir).expanduser().resolve()
        tokenizer_path = Path(args.tokenizer_dir).expanduser().resolve()

        if not input_path.is_file():
            raise FileNotFoundError(f"Input CSV not found: {input_path}")
        if not model_path.is_dir():
            raise FileNotFoundError(
                f"CTranslate2 model directory not found: {model_path}"
            )
        if not tokenizer_path.is_dir():
            raise FileNotFoundError(
                f"Tokenizer directory not found: {tokenizer_path}"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        rows, original_fields = read_rows(
            input_path,
            start_row=args.start_row,
            limit=args.limit,
        )
        if not rows:
            raise ValueError("No rows were selected from the input CSV.")

        input_column = find_column(
            original_fields,
            args.input_column,
            ["input"],
            required=True,
        )
        expected_column = find_column(
            original_fields,
            args.expected_column,
            ["expected_output", "Correct Sentence", "correct_sentence"],
            required=False,
        )
        use_case_column = find_column(
            original_fields,
            args.use_case_column,
            ["use_case", "Use Case"],
            required=False,
        )

        nonblank_rows = [
            row for row in rows if (row.get(input_column) or "").strip()
        ]
        skipped = len(rows) - len(nonblank_rows)
        rows = nonblank_rows

        print(f"CTranslate2 version: {ctranslate2.__version__}")
        print(
            "Supported CPU compute types:",
            ctranslate2.get_supported_compute_types("cpu"),
        )
        print(f"Selected rows: {len(rows)}")
        if skipped:
            print(f"Skipped blank inputs: {skipped}")
        print(f"Input column: {input_column}")
        print(f"Expected column: {expected_column or 'not available'}")
        print(f"Use-case column: {use_case_column or 'not available'}")
        print(f"Batch size: {args.batch_size}")
        print(f"CPU threads: {args.threads}")
        print()

        print("Loading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            str(tokenizer_path),
            local_files_only=True,
        )
        print(f"Tokenizer: {type(tokenizer).__name__}")

        print("Loading CTranslate2 model...")
        translator = ctranslate2.Translator(
            str(model_path),
            device="cpu",
            compute_type=args.compute_type,
            inter_threads=args.inter_threads,
            intra_threads=args.threads,
        )
        print(
            f"Model loaded. Active compute type: {translator.compute_type}\n"
        )

        completed = 0
        run_start = time.perf_counter()

        for chunk_start, batch_rows in chunks(rows, args.batch_size):
            source_tokens = tokenize_inputs(
                batch_rows,
                input_column=input_column,
                tokenizer=tokenizer,
                prefix=args.prefix,
                max_input_length=args.max_input_length,
            )

            batch_started = time.perf_counter()
            try:
                results = translator.translate_batch(
                    source_tokens,
                    max_batch_size=args.batch_size,
                    batch_type="examples",
                    beam_size=args.beam_size,
                    max_input_length=args.max_input_length,
                    max_decoding_length=args.max_decoding_length,
                )
                batch_elapsed = time.perf_counter() - batch_started
                average_elapsed = batch_elapsed / len(batch_rows)

                for row, result in zip(batch_rows, results):
                    output = decode_result(result, tokenizer)
                    expected = (
                        (row.get(expected_column) or "").strip()
                        if expected_column
                        else ""
                    )

                    row["ct2_output"] = output
                    row["ct2_status"] = "success"
                    row["ct2_batch_time_seconds"] = f"{batch_elapsed:.6f}"
                    row["ct2_avg_time_per_item_seconds"] = (
                        f"{average_elapsed:.6f}"
                    )
                    row["ct2_exact_match"] = (
                        str(output == expected) if expected_column else ""
                    )
                    row["ct2_normalized_match"] = (
                        str(normalize_text(output) == normalize_text(expected))
                        if expected_column
                        else ""
                    )
                    similarity = (
                        similarity_percent(output, expected)
                        if expected_column
                        else None
                    )
                    row["ct2_similarity_percent"] = (
                        "" if similarity is None else f"{similarity:.2f}"
                    )
                    row["ct2_error"] = ""

            except Exception as error:
                batch_elapsed = time.perf_counter() - batch_started
                average_elapsed = batch_elapsed / len(batch_rows)

                # Record the batch error and continue writing a usable CSV.
                for row in batch_rows:
                    row["ct2_output"] = ""
                    row["ct2_status"] = "error"
                    row["ct2_batch_time_seconds"] = f"{batch_elapsed:.6f}"
                    row["ct2_avg_time_per_item_seconds"] = (
                        f"{average_elapsed:.6f}"
                    )
                    row["ct2_exact_match"] = ""
                    row["ct2_normalized_match"] = ""
                    row["ct2_similarity_percent"] = ""
                    row["ct2_error"] = f"{type(error).__name__}: {error}"

            completed += len(batch_rows)
            if (
                completed % args.progress_every == 0
                or completed == len(rows)
            ):
                elapsed = time.perf_counter() - run_start
                print(
                    f"Completed {completed}/{len(rows)} "
                    f"({elapsed:.2f} seconds elapsed)"
                )

        total_elapsed = time.perf_counter() - run_start
        summary_path = make_summary_path(output_path)

        write_detailed_results(
            output_path,
            rows,
            original_fields=original_fields,
        )
        write_summary(
            summary_path,
            rows,
            use_case_column=use_case_column,
        )

        successful = sum(row["ct2_status"] == "success" for row in rows)
        errors = len(rows) - successful

        print("\nRun complete")
        print(f"Successful rows: {successful}")
        print(f"Error rows: {errors}")
        print(f"Total inference time: {total_elapsed:.3f} seconds")
        if rows:
            print(
                "Overall wall-clock average: "
                f"{total_elapsed / len(rows):.4f} seconds/case"
            )
        print(f"Detailed results: {output_path}")
        print(f"Use-case summary: {summary_path}")

        return 0 if errors == 0 else 2

    except Exception as error:
        print(
            f"ERROR: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
