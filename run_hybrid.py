#!/home/abhiram.nagaraj/Downloads/grammar-correction-ct2/.venv/bin/python
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from grammar.config import load_app_config
from grammar.correction_router import CorrectionRouter


BASE_DIR = Path(__file__).resolve().parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Conservative hybrid grammar correction pipeline."
    )
    parser.add_argument("sentence", nargs="*", help="Sentence to correct.")
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run in interactive mode.",
    )
    parser.add_argument("--file", help="CSV file to process.")
    parser.add_argument(
        "--output-file",
        default="grammar_results.csv",
        help="CSV output file. Default: grammar_results.csv",
    )
    parser.add_argument(
        "--input-column",
        default="input",
        help="CSV column containing the sentence to correct.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        help="CPU inference threads for Qwen. Default: 8.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N rows from the CSV.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print the structured decision payload.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON.",
    )
    return parser


def _print_result(result, details: bool, as_json: bool) -> None:
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not details:
        print(result.final_text)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_interactive(router: CorrectionRouter, details: bool, as_json: bool) -> None:
    print()
    print("Model is ready.")
    print("Type a sentence and press Enter.")
    print("Type exit to stop.")
    print()

    while True:
        try:
            sentence = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not sentence:
            continue
        if sentence.casefold() in {"exit", "quit", ":q"}:
            break

        result = router.correct(sentence)
        _print_result(result, details, as_json)


def run_csv(
    router: CorrectionRouter,
    input_file: str,
    output_file: str,
    input_column: str,
    limit: int | None,
) -> None:
    input_path = Path(input_file).expanduser().resolve()
    output_path = Path(output_file).expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {input_path}")

    with input_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("The CSV has no header row.")
        if input_column not in reader.fieldnames:
            raise ValueError(
                f"Input column {input_column!r} not found. Available columns: {list(reader.fieldnames)}"
            )

        rows = list(reader)
        if limit is not None:
            rows = rows[:limit]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(reader.fieldnames)
    extras = [
        "hybrid_output",
        "decision",
        "source",
        "changed",
        "suggestions",
        "accepted_edits",
        "rejected_edits",
        "validation",
        "reasons",
        "request_id",
    ]
    for extra in extras:
        if extra not in fieldnames:
            fieldnames.append(extra)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            result = router.correct((row.get(input_column) or "").strip())
            payload = result.to_dict()
            row["hybrid_output"] = result.final_text
            row["decision"] = result.decision
            row["source"] = result.source
            row["changed"] = result.changed
            row["suggestions"] = json.dumps(payload["suggestions"], ensure_ascii=False)
            row["accepted_edits"] = json.dumps(payload["accepted_edits"], ensure_ascii=False)
            row["rejected_edits"] = json.dumps(payload["rejected_edits"], ensure_ascii=False)
            row["validation"] = json.dumps(payload["validation"], ensure_ascii=False)
            row["reasons"] = json.dumps(payload["reasons"], ensure_ascii=False)
            row["request_id"] = payload["request_id"]
            writer.writerow(row)
            print(f"Processed row {index}")

    print(f"\nResults saved to: {output_path}")


def main() -> None:
    args = build_parser().parse_args()

    if not args.interactive and not args.file and not args.sentence:
        print(
            "Usage:\n"
            '  ./check "Sentence to correct"\n'
            "  ./check --interactive\n"
            "  ./check --file input.csv",
            file=sys.stderr,
        )
        raise SystemExit(1)

    config = load_app_config()
    router = CorrectionRouter(config=config, qwen_threads=args.threads)

    if args.interactive:
        run_interactive(router, args.details, args.json)
        return

    if args.file:
        run_csv(
            router=router,
            input_file=args.file,
            output_file=args.output_file,
            input_column=args.input_column,
            limit=args.limit,
        )
        return

    sentence = " ".join(args.sentence).strip()
    result = router.correct(sentence)
    _print_result(result, args.details, args.json)


if __name__ == "__main__":
    main()
