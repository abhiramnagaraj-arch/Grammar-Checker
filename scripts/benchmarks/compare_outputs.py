#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare model output with expected output."
    )

    parser.add_argument(
        "--input-file",
        required=True,
        help="Input CSV or XLSX result file.",
    )

    parser.add_argument(
        "--output-file",
        required=True,
        help="Output CSV or XLSX file.",
    )

    parser.add_argument(
        "--expected-column",
        default="expected_output",
        help="Column containing the expected output.",
    )

    parser.add_argument(
        "--model-column",
        default="qwen_output",
        help="Column containing the model output.",
    )

    parser.add_argument(
        "--use-case-column",
        default="use_case",
        help="Optional category/use-case column.",
    )

    return parser.parse_args()


def load_file(path: Path) -> pd.DataFrame:
    extension = path.suffix.lower()

    if extension == ".csv":
        return pd.read_csv(path)

    if extension in {".xlsx", ".xls"}:
        return pd.read_excel(path)

    raise ValueError(
        "Unsupported file type. Use CSV, XLSX, or XLS."
    )


def normalize_text(text: object) -> str:
    if pd.isna(text):
        return ""

    value = str(text)

    value = unicodedata.normalize("NFKC", value)

    value = (
        value.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )

    value = re.sub(r"\s+", " ", value).strip()

    return value.casefold()


def normalize_relaxed(text: object) -> str:
    value = normalize_text(text)

    # Ignore final punctuation differences.
    value = re.sub(r"[.!?]+$", "", value).strip()

    return value


def similarity_percent(
    actual: object,
    expected: object,
) -> float:
    actual_normalized = normalize_text(actual)
    expected_normalized = normalize_text(expected)

    if not expected_normalized:
        return 0.0

    score = SequenceMatcher(
        None,
        actual_normalized,
        expected_normalized,
    ).ratio()

    return round(score * 100, 2)


def save_file(
    dataframe: pd.DataFrame,
    summary: pd.DataFrame,
    path: Path,
) -> None:
    extension = path.suffix.lower()

    if extension == ".csv":
        dataframe.to_csv(
            path,
            index=False,
            encoding="utf-8-sig",
        )

        summary_path = path.with_name(
            f"{path.stem}_summary.csv"
        )

        summary.to_csv(
            summary_path,
            index=False,
            encoding="utf-8-sig",
        )

        print("Summary file:", summary_path)
        return

    if extension in {".xlsx", ".xls"}:
        with pd.ExcelWriter(
            path,
            engine="openpyxl",
        ) as writer:
            dataframe.to_excel(
                writer,
                sheet_name="Comparison",
                index=False,
            )

            summary.to_excel(
                writer,
                sheet_name="Summary",
                index=False,
            )

        return

    raise ValueError(
        "Output file must be CSV or XLSX."
    )


def build_summary(
    dataframe: pd.DataFrame,
    use_case_column: str,
) -> pd.DataFrame:
    summary_rows: list[dict[str, object]] = []

    if use_case_column in dataframe.columns:
        grouped = dataframe.groupby(
            use_case_column,
            dropna=False,
        )

        for use_case, group in grouped:
            total = len(group)

            exact_matches = int(
                (group["exact_match"] == "Yes").sum()
            )

            normalized_matches = int(
                (group["normalized_match"] == "Yes").sum()
            )

            relaxed_matches = int(
                (group["relaxed_match"] == "Yes").sum()
            )

            summary_rows.append(
                {
                    "use_case": (
                        use_case
                        if pd.notna(use_case)
                        else "UNSPECIFIED"
                    ),
                    "total_cases": total,
                    "exact_matches": exact_matches,
                    "exact_success_rate": round(
                        exact_matches / total * 100,
                        2,
                    ),
                    "normalized_matches": normalized_matches,
                    "normalized_success_rate": round(
                        normalized_matches / total * 100,
                        2,
                    ),
                    "relaxed_matches": relaxed_matches,
                    "relaxed_success_rate": round(
                        relaxed_matches / total * 100,
                        2,
                    ),
                    "average_similarity_percent": round(
                        group["similarity_percent"].mean(),
                        2,
                    ),
                }
            )

    total = len(dataframe)

    exact_matches = int(
        (dataframe["exact_match"] == "Yes").sum()
    )

    normalized_matches = int(
        (dataframe["normalized_match"] == "Yes").sum()
    )

    relaxed_matches = int(
        (dataframe["relaxed_match"] == "Yes").sum()
    )

    summary_rows.append(
        {
            "use_case": "__OVERALL__",
            "total_cases": total,
            "exact_matches": exact_matches,
            "exact_success_rate": round(
                exact_matches / total * 100,
                2,
            ) if total else 0,
            "normalized_matches": normalized_matches,
            "normalized_success_rate": round(
                normalized_matches / total * 100,
                2,
            ) if total else 0,
            "relaxed_matches": relaxed_matches,
            "relaxed_success_rate": round(
                relaxed_matches / total * 100,
                2,
            ) if total else 0,
            "average_similarity_percent": round(
                dataframe["similarity_percent"].mean(),
                2,
            ) if total else 0,
        }
    )

    return pd.DataFrame(summary_rows)


def main() -> None:
    args = parse_arguments()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    dataframe = load_file(input_path)

    if args.expected_column not in dataframe.columns:
        raise ValueError(
            f"Expected column not found: "
            f"{args.expected_column}\n"
            f"Available columns: "
            f"{list(dataframe.columns)}"
        )

    if args.model_column not in dataframe.columns:
        raise ValueError(
            f"Model output column not found: "
            f"{args.model_column}\n"
            f"Available columns: "
            f"{list(dataframe.columns)}"
        )

    expected_values = dataframe[
        args.expected_column
    ].fillna("")

    model_values = dataframe[
        args.model_column
    ].fillna("")

    dataframe["exact_match"] = [
        "Yes" if str(actual) == str(expected) else "No"
        for actual, expected in zip(
            model_values,
            expected_values,
        )
    ]

    dataframe["normalized_match"] = [
        (
            "Yes"
            if normalize_text(actual)
            == normalize_text(expected)
            else "No"
        )
        for actual, expected in zip(
            model_values,
            expected_values,
        )
    ]

    dataframe["relaxed_match"] = [
        (
            "Yes"
            if normalize_relaxed(actual)
            == normalize_relaxed(expected)
            else "No"
        )
        for actual, expected in zip(
            model_values,
            expected_values,
        )
    ]

    dataframe["similarity_percent"] = [
        similarity_percent(actual, expected)
        for actual, expected in zip(
            model_values,
            expected_values,
        )
    ]

    summary = build_summary(
        dataframe,
        args.use_case_column,
    )

    save_file(
        dataframe,
        summary,
        output_path,
    )

    overall = summary[
        summary["use_case"] == "__OVERALL__"
    ].iloc[0]

    print("\nComparison completed")
    print("Total cases:", int(overall["total_cases"]))

    print(
        "Exact matches:",
        int(overall["exact_matches"]),
    )
    print(
        "Exact success rate:",
        f"{overall['exact_success_rate']:.2f}%",
    )

    print(
        "Normalized matches:",
        int(overall["normalized_matches"]),
    )
    print(
        "Normalized success rate:",
        f"{overall['normalized_success_rate']:.2f}%",
    )

    print(
        "Relaxed matches:",
        int(overall["relaxed_matches"]),
    )
    print(
        "Relaxed success rate:",
        f"{overall['relaxed_success_rate']:.2f}%",
    )

    print(
        "Average similarity:",
        f"{overall['average_similarity_percent']:.2f}%",
    )

    print("Output file:", output_path)


if __name__ == "__main__":
    main()
