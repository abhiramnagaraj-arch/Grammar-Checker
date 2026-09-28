from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\bhttps?://[^\s<>()]+\b|\bwww\.[^\s<>()]+\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"""
    (?<!\w)
    (?:\+?\d{1,3}[-.\s]?)?
    (?:\(?\d{3}\)?[-.\s]?)?
    \d{3}[-.\s]?\d{4}
    (?!\w)
    """,
    re.VERBOSE,
)
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b|\b\d{1,2}\s?[AP]M\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b")
CURRENCY_RE = re.compile(r"[$€£₹]\s?\d+(?:,\d{3})*(?:\.\d+)?")
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?%\b")
VERSION_RE = re.compile(r"\bv?\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?\b")
FILE_RE = re.compile(r"\b[\w.-]+\.(?:txt|csv|json|yaml|yml|xml|html|htm|py|js|ts|java|md|pdf|docx?|xlsx?)\b", re.IGNORECASE)
TICKET_RE = re.compile(r"\b[A-Z]{2,}-\d+\b|\b#[0-9a-f]{6,}\b", re.IGNORECASE)
CODE_RE = re.compile(r"`[^`]+`|\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
NEGATION_RE = re.compile(r"\b(?:not|never|no|cannot|can’t|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|shouldn't|wouldn't|couldn't|mustn't)\b", re.IGNORECASE)
EMAIL_THREAD_RE = re.compile(r"^(?:>+|On .+ wrote:|From:|Sent:|Subject:)", re.IGNORECASE)
SIGNATURE_RE = re.compile(r"^--\s*$|^(?:Thanks|Regards|Best|Sincerely|Cheers),?$", re.IGNORECASE)
TABLE_ROW_RE = re.compile(r"\|.+\|")


@dataclass(slots=True)
class Span:
    start: int
    end: int
    label: str


def _collect(pattern: re.Pattern[str], text: str, label: str) -> list[Span]:
    return [Span(m.start(), m.end(), label) for m in pattern.finditer(text)]


def extract_protected_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for pattern, label in [
        (EMAIL_RE, "email"),
        (URL_RE, "url"),
        (PHONE_RE, "phone"),
        (DATE_RE, "date"),
        (TIME_RE, "time"),
        (CURRENCY_RE, "currency"),
        (PERCENT_RE, "percent"),
        (VERSION_RE, "version"),
        (FILE_RE, "file"),
        (TICKET_RE, "ticket"),
        (CODE_RE, "code"),
    ]:
        spans.extend(_collect(pattern, text, label))
    return merge_spans(spans)


def extract_negation_spans(text: str) -> list[Span]:
    return _collect(NEGATION_RE, text, "negation")


def has_thread_or_signature_markers(text: str) -> bool:
    lines = [line.rstrip() for line in text.splitlines()]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if EMAIL_THREAD_RE.match(stripped):
            return True
        if SIGNATURE_RE.match(stripped):
            return True
        if stripped.startswith("```") or stripped.startswith("    "):
            return True
        if TABLE_ROW_RE.search(stripped):
            return True
    return False


def is_skippable_email_like_text(text: str) -> bool:
    return has_thread_or_signature_markers(text)


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    ordered = sorted(spans, key=lambda item: (item.start, item.end))
    if not ordered:
        return []

    merged: list[Span] = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start <= last.end:
            merged[-1] = Span(last.start, max(last.end, span.end), last.label)
        else:
            merged.append(span)
    return merged


def spans_overlap(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def has_span_overlap(spans: list[Span]) -> bool:
    ordered = sorted(spans, key=lambda item: (item.start, item.end))
    for left, right in zip(ordered, ordered[1:]):
        if spans_overlap(left, right):
            return True
    return False


def compare_protected_values(original: str, candidate: str) -> dict[str, bool]:
    checks = {
        "emails": EMAIL_RE.findall(original) == EMAIL_RE.findall(candidate),
        "urls": URL_RE.findall(original) == URL_RE.findall(candidate),
        "phones": PHONE_RE.findall(original) == PHONE_RE.findall(candidate),
        "dates": DATE_RE.findall(original) == DATE_RE.findall(candidate),
        "times": TIME_RE.findall(original) == TIME_RE.findall(candidate),
        "numbers": NUMBER_RE.findall(original) == NUMBER_RE.findall(candidate),
        "currency": CURRENCY_RE.findall(original) == CURRENCY_RE.findall(candidate),
        "percent": PERCENT_RE.findall(original) == PERCENT_RE.findall(candidate),
        "versions": VERSION_RE.findall(original) == VERSION_RE.findall(candidate),
        "files": FILE_RE.findall(original) == FILE_RE.findall(candidate),
        "tickets": TICKET_RE.findall(original) == TICKET_RE.findall(candidate),
        "code": CODE_RE.findall(original) == CODE_RE.findall(candidate),
        "negation": NEGATION_RE.findall(original) == NEGATION_RE.findall(candidate),
    }
    return checks

