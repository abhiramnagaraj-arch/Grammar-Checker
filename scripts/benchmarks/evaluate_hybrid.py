#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class EvalCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    auto_apply_precision_hits: int = 0
    auto_apply_precision_total: int = 0
    unsafe_changes: int = 0
    total: int = 0

    def precision(self) -> float:
        denom = self.tp + self.fp
        return 0.0 if denom == 0 else self.tp / denom

    def recall(self) -> float:
        denom = self.tp + self.fn
        return 0.0 if denom == 0 else self.tp / denom

    def f1(self) -> float:
        precision = self.precision()
        recall = self.recall()
        denom = precision + recall
        return 0.0 if denom == 0 else 2 * precision * recall / denom

    def accuracy(self) -> float:
        denom = self.tp + self.fp + self.fn + self.tn
        return 0.0 if denom == 0 else (self.tp + self.tn) / denom

    def auto_apply_precision(self) -> float:
        return 0.0 if self.auto_apply_precision_total == 0 else self.auto_apply_precision_hits / self.auto_apply_precision_total

    def unsafe_change_rate(self) -> float:
        return 0.0 if self.total == 0 else self.unsafe_changes / self.total


def _read_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _normalize(value: str | None) -> str:
    return (value or "").strip()


def evaluate(rows: Iterable[dict[str, str]]) -> EvalCounts:
    counts = EvalCounts()
    for row in rows:
        original = _normalize(row.get("original"))
        expected = _normalize(row.get("expected"))
        prediction = _normalize(row.get("prediction"))
        human_label = _normalize(row.get("human_label")).casefold()
        decision = _normalize(row.get("decision")).casefold()

        changed = prediction != original
        expected_changed = expected != original
        unsafe = _normalize(row.get("unsafe_change")).casefold() in {"1", "true", "yes"}
        auto_applied = decision == "auto_apply"

        counts.total += 1
        if changed and expected_changed:
            counts.tp += 1
        elif changed and not expected_changed:
            counts.fp += 1
        elif not changed and expected_changed:
            counts.fn += 1
        else:
            counts.tn += 1

        if auto_applied:
            counts.auto_apply_precision_total += 1
            if human_label in {"correct", "safe", "accept", "yes"} and not unsafe:
                counts.auto_apply_precision_hits += 1

        if unsafe:
            counts.unsafe_changes += 1

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate hybrid grammar correction outputs.")
    parser.add_argument("--input", required=True, type=Path, help="CSV or JSONL file with original/expected/prediction columns.")
    args = parser.parse_args()

    rows = _read_rows(args.input)
    counts = evaluate(rows)
    print(json.dumps(
        {
            "tp": counts.tp,
            "fp": counts.fp,
            "fn": counts.fn,
            "tn": counts.tn,
            "precision": round(counts.precision(), 4),
            "recall": round(counts.recall(), 4),
            "f1": round(counts.f1(), 4),
            "accuracy": round(counts.accuracy(), 4),
            "auto_apply_precision": round(counts.auto_apply_precision(), 4),
            "unsafe_change_rate": round(counts.unsafe_change_rate(), 4),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
