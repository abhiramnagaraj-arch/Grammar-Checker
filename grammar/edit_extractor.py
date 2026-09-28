from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from grammar.correction_models import Edit


TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


@dataclass(slots=True)
class TokenSpan:
    token: str
    start: int
    end: int


def tokenize_with_spans(text: str) -> list[TokenSpan]:
    return [TokenSpan(match.group(0), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def extract_edits(original: str, candidate: str) -> list[Edit]:
    original_tokens = tokenize_with_spans(original)
    candidate_tokens = tokenize_with_spans(candidate)
    original_values = [token.token for token in original_tokens]
    candidate_values = [token.token for token in candidate_tokens]
    matcher = difflib.SequenceMatcher(None, original_values, candidate_values)
    edits: list[Edit] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        original_start = original_tokens[i1].start if i1 < len(original_tokens) else len(original)
        original_end = original_tokens[i2 - 1].end if i2 > i1 and i2 - 1 < len(original_tokens) else original_start
        candidate_start = candidate_tokens[j1].start if j1 < len(candidate_tokens) else len(candidate)
        candidate_end = candidate_tokens[j2 - 1].end if j2 > j1 and j2 - 1 < len(candidate_tokens) else candidate_start

        if tag == "replace":
            operation = "replace"
        elif tag == "insert":
            operation = "insert"
        elif tag == "delete":
            operation = "delete"
        else:
            continue

        edits.append(
            Edit(
                operation=operation,
                original_text=original[original_start:original_end],
                replacement_text=candidate[candidate_start:candidate_end],
                original_start=original_start,
                original_end=original_end,
                candidate_start=candidate_start,
                candidate_end=candidate_end,
            )
        )

    return edits


def apply_edits(original: str, edits: list[Edit]) -> str:
    if not edits:
        return original

    updated = original
    for edit in sorted(edits, key=lambda item: (item.original_start, item.original_end), reverse=True):
        updated = updated[: edit.original_start] + edit.replacement_text + updated[edit.original_end :]
    return updated
