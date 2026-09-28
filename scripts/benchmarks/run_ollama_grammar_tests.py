#!/usr/bin/env python3

import argparse
import csv
import json
import time
import urllib.request
from datetime import timedelta
from pathlib import Path


SYSTEM_PROMPT = """You are a strict grammar-correction assistant.

Rules:
- Correct only grammatical, punctuation, article, tense, agreement, and preposition errors.
- Preserve the original meaning and wording.
- Preserve names, numbers, dates, versions, email addresses, URLs, technical terms, negation, and words such as "only".
- Do not rewrite for style.
- Do not add explanations.
- Return only the corrected sentence.
- If the sentence is already correct, return it unchanged.
"""


def format_time(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def call_ollama(
    model: str,
    sentence: str,
    timeout: int,
    temperature: float,
) -> tuple[str, float]:
    payload = {
        "model": model,
        "prompt": f"{SYSTEM_PROMPT}\nSentence:\n{sentence}",
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "seed": 42,
        },
    }

    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    inference_started = time.perf_counter()

    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))

    inference_time = time.perf_counter() - inference_started
    model_output = result.get("response", "").strip()

    return model_output, inference_time


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run grammar test cases against an Ollama model."
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Ollama model name, for example gemma2:2b",
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input CSV file",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Detailed CSV report",
    )

    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Summary TXT report",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N rows",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout per test case",
    )

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Generation temperature",
    )

    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(
            f"Input CSV not found: {args.input}"
        )

    safe_model_name = (
        args.model
        .replace("/", "_")
        .replace(":", "_")
    )

    output_path = args.output or Path(
        f"results/{safe_model_name}_grammar_results.csv"
    )

    summary_path = args.summary_output or Path(
        f"results/{safe_model_name}_grammar_summary.txt"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with args.input.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as input_file:
        reader = csv.DictReader(input_file)

        required_columns = {
            "test_id",
            "input",
            "expected_output",
            "use_case",
        }

        available_columns = set(
            reader.fieldnames or []
        )

        missing_columns = (
            required_columns - available_columns
        )

        if missing_columns:
            raise ValueError(
                "Missing required columns: "
                f"{sorted(missing_columns)}"
            )

        rows = list(reader)

    if args.limit is not None:
        rows = rows[:args.limit]

    output_columns = [
        "test_id",
        "use_case",
        "input",
        "expected_output",
        "model_output",
        "exact_match",
        "normalized_match",
        "changed_input",
        "inference_seconds",
        "case_total_seconds",
        "elapsed_total_seconds",
        "estimated_remaining_seconds",
        "status",
        "error",
        "model",
    ]

    passed = 0
    review_needed = 0
    errors = 0

    total_inference_time = 0.0
    completed_cases = 0

    overall_started = time.perf_counter()
    total_cases = len(rows)

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=output_columns,
        )

        writer.writeheader()

        for index, row in enumerate(rows, start=1):
            sentence = row["input"].strip()
            expected = row["expected_output"].strip()

            print(
                f"[{index}/{total_cases}] "
                f"Test {row['test_id']}: "
                f"{sentence[:70]}"
            )

            case_started = time.perf_counter()

            report_row = {
                "test_id": row["test_id"],
                "use_case": row["use_case"],
                "input": sentence,
                "expected_output": expected,
                "model_output": "",
                "exact_match": False,
                "normalized_match": False,
                "changed_input": False,
                "inference_seconds": "",
                "case_total_seconds": "",
                "elapsed_total_seconds": "",
                "estimated_remaining_seconds": "",
                "status": "ERROR",
                "error": "",
                "model": args.model,
            }

            try:
                model_output, inference_time = call_ollama(
                    model=args.model,
                    sentence=sentence,
                    timeout=args.timeout,
                    temperature=args.temperature,
                )

                case_total_time = (
                    time.perf_counter() - case_started
                )

                completed_cases += 1
                total_inference_time += inference_time

                total_elapsed = (
                    time.perf_counter() - overall_started
                )

                average_time_so_far = (
                    total_elapsed / completed_cases
                )

                remaining_cases = (
                    total_cases - index
                )

                estimated_remaining = (
                    average_time_so_far
                    * remaining_cases
                )

                exact_match = (
                    model_output == expected
                )

                normalized_match = (
                    normalize(model_output)
                    == normalize(expected)
                )

                status = (
                    "PASS"
                    if normalized_match
                    else "REVIEW"
                )

                if normalized_match:
                    passed += 1
                else:
                    review_needed += 1

                report_row.update(
                    {
                        "model_output": model_output,
                        "exact_match": exact_match,
                        "normalized_match": normalized_match,
                        "changed_input": (
                            model_output != sentence
                        ),
                        "inference_seconds": (
                            f"{inference_time:.4f}"
                        ),
                        "case_total_seconds": (
                            f"{case_total_time:.4f}"
                        ),
                        "elapsed_total_seconds": (
                            f"{total_elapsed:.4f}"
                        ),
                        "estimated_remaining_seconds": (
                            f"{estimated_remaining:.4f}"
                        ),
                        "status": status,
                    }
                )

                print(
                    f"    Output: {model_output}"
                )

                print(
                    f"    Status: {status} | "
                    f"Case: {case_total_time:.3f}s | "
                    f"Total: {format_time(total_elapsed)} | "
                    f"ETA: {format_time(estimated_remaining)}"
                )

            except Exception as error:
                completed_cases += 1
                errors += 1

                case_total_time = (
                    time.perf_counter() - case_started
                )

                total_elapsed = (
                    time.perf_counter() - overall_started
                )

                average_time_so_far = (
                    total_elapsed / completed_cases
                )

                remaining_cases = (
                    total_cases - index
                )

                estimated_remaining = (
                    average_time_so_far
                    * remaining_cases
                )

                report_row.update(
                    {
                        "case_total_seconds": (
                            f"{case_total_time:.4f}"
                        ),
                        "elapsed_total_seconds": (
                            f"{total_elapsed:.4f}"
                        ),
                        "estimated_remaining_seconds": (
                            f"{estimated_remaining:.4f}"
                        ),
                        "error": str(error),
                    }
                )

                print(
                    f"    ERROR: {error}"
                )

                print(
                    f"    Case: {case_total_time:.3f}s | "
                    f"Total: {format_time(total_elapsed)} | "
                    f"ETA: {format_time(estimated_remaining)}"
                )

            writer.writerow(report_row)

            # Save after every row so progress is not lost.
            output_file.flush()

    total_elapsed = (
        time.perf_counter() - overall_started
    )

    evaluated_cases = (
        passed + review_needed
    )

    match_rate = (
        passed / evaluated_cases * 100
        if evaluated_cases
        else 0.0
    )

    average_inference_time = (
        total_inference_time / evaluated_cases
        if evaluated_cases
        else 0.0
    )

    average_total_time = (
        total_elapsed / completed_cases
        if completed_cases
        else 0.0
    )

    summary_lines = [
        "==========================================",
        "OLLAMA GRAMMAR TEST SUMMARY",
        "==========================================",
        f"Model                   : {args.model}",
        f"Input file              : {args.input}",
        f"Detailed CSV report     : {output_path}",
        f"Total test cases        : {total_cases}",
        f"Passed                  : {passed}",
        f"Review needed           : {review_needed}",
        f"Errors                  : {errors}",
        f"Normalized match rate   : {match_rate:.2f}%",
        f"Total elapsed time      : {format_time(total_elapsed)}",
        f"Total elapsed seconds   : {total_elapsed:.3f}",
        f"Average inference/case  : {average_inference_time:.3f}s",
        f"Average total/case      : {average_total_time:.3f}s",
        "==========================================",
    ]

    summary_text = "\n".join(summary_lines)

    with summary_path.open(
        "w",
        encoding="utf-8",
    ) as summary_file:
        summary_file.write(summary_text + "\n")

    print()
    print(summary_text)
    print(f"Summary TXT saved       : {summary_path}")


if __name__ == "__main__":
    main()
