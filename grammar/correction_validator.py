from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import Sequence

from grammar.config import ValidationThresholds
from grammar.correction_models import Edit, LanguageToolFinding, ValidationSignals
from grammar.edit_extractor import extract_edits
from grammar.protected_content import compare_protected_values, extract_negation_spans, extract_protected_spans


SAFE_REPLACEMENT_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "am",
    "be",
    "been",
    "being",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "from",
    "with",
    "and",
    "or",
    "but",
    "not",
}
SAFE_INSERTION_WORDS = {"a", "an", "the"}
REPEATED_WORD_RE = re.compile(r"^(\w+)(?:\s+\1)+$", re.IGNORECASE)
PUNCT_RE = re.compile(r"^[^\w\s]+$")


@dataclass(slots=True)
class ValidationOutcome:
    accepted_edits: list[Edit] = field(default_factory=list)
    rejected_edits: list[Edit] = field(default_factory=list)
    final_text: str = ""
    keep_original: bool = True
    reasons: list[str] = field(default_factory=list)
    signals: ValidationSignals = field(default_factory=ValidationSignals)


class CorrectionValidator:
    def __init__(self, thresholds: ValidationThresholds) -> None:
        self.thresholds = thresholds

    def _character_edit_ratio(self, original: str, candidate: str) -> float:
        if not original:
            return 0.0
        matcher = SequenceMatcher(None, original, candidate)
        return 1.0 - matcher.ratio()

    def _changed_word_ratio(self, original: str, candidate: str) -> float:
        original_words = original.split()
        candidate_words = candidate.split()
        if not original_words:
            return 0.0
        matcher = SequenceMatcher(None, original_words, candidate_words)
        return 1.0 - matcher.ratio()

    def _length_ratio(self, original: str, candidate: str) -> float:
        original_length = max(len(original), 1)
        return len(candidate) / original_length

    def validate_candidate(
        self,
        original: str,
        candidate: str,
        errors_before: int = 0,
        errors_after: int = 0,
    ) -> ValidationSignals:
        signals = ValidationSignals(
            errors_before=errors_before,
            errors_after=errors_after,
            protected_content_preserved=True,
            numbers_preserved=True,
            negation_preserved=True,
        )
        signals.character_edit_ratio = self._character_edit_ratio(original, candidate)
        signals.changed_word_ratio = self._changed_word_ratio(original, candidate)
        signals.length_ratio = self._length_ratio(original, candidate)
        protected = compare_protected_values(original, candidate)
        signals.protected_content_preserved = all(protected.values())
        signals.numbers_preserved = protected["numbers"]
        signals.negation_preserved = protected["negation"]
        signals.target_findings_removed = errors_after < errors_before
        signals.new_findings_introduced = errors_after > errors_before
        return signals

    def hard_reject(self, original: str, candidate: str, reasons: list[str] | None = None) -> list[str]:
        reasons = [] if reasons is None else reasons
        if not candidate.strip():
            reasons.append("candidate_empty")
        if candidate != candidate.strip():
            reasons.append("leading_or_trailing_whitespace")
        protected = compare_protected_values(original, candidate)
        if not all(protected.values()):
            for name, ok in protected.items():
                if not ok:
                    reasons.append(f"protected_{name}_changed")
        if self._length_ratio(original, candidate) < self.thresholds.min_length_ratio:
            reasons.append("candidate_too_short")
        if self._length_ratio(original, candidate) > self.thresholds.max_length_ratio:
            reasons.append("candidate_too_long")
        if self._character_edit_ratio(original, candidate) > self.thresholds.max_character_edit_ratio:
            reasons.append("character_edit_ratio_exceeded")
        if self._changed_word_ratio(original, candidate) > self.thresholds.max_changed_word_ratio:
            reasons.append("changed_word_ratio_exceeded")
        if extract_negation_spans(original) and len(extract_negation_spans(original)) != len(extract_negation_spans(candidate)):
            reasons.append("negation_changed")
        return reasons

    def _is_safe_lexical_edit(self, original: str, edit: Edit) -> bool:
        span_original = edit.original_text.strip()
        replacement = edit.replacement_text.strip()

        if not span_original and replacement in SAFE_INSERTION_WORDS:
            return True
        if edit.operation == "delete":
            span_text = span_original
            if REPEATED_WORD_RE.match(span_text):
                return True
            if PUNCT_RE.match(span_text):
                return True
            deleted_word = span_text.casefold()
            if deleted_word and deleted_word in SAFE_INSERTION_WORDS:
                prefix = original[: edit.original_start].rstrip()
                previous_word = prefix.split()[-1].casefold() if prefix.split() else ""
                if previous_word == deleted_word:
                    return True
            return False
        if edit.operation == "insert":
            if replacement in SAFE_INSERTION_WORDS:
                return True
            if PUNCT_RE.match(replacement):
                return True
            return False
        if edit.operation == "replace":
            if span_original.lower() in SAFE_REPLACEMENT_WORDS and replacement.lower() in SAFE_REPLACEMENT_WORDS:
                return True
            if PUNCT_RE.match(span_original) and PUNCT_RE.match(replacement):
                return True
            if span_original.lower() == replacement.lower():
                return True
        return False

    def apply_and_validate_edits(
        self,
        original: str,
        candidate: str,
        errors_before: int = 0,
        errors_after: int = 0,
        lt_findings: Sequence[LanguageToolFinding] | None = None,
    ) -> ValidationOutcome:
        reasons = self.hard_reject(original, candidate, [])
        signals = self.validate_candidate(original, candidate, errors_before, errors_after)
        critical_reasons = [
            reason
            for reason in reasons
            if reason
            not in {
                "character_edit_ratio_exceeded",
                "changed_word_ratio_exceeded",
            }
        ]
        if critical_reasons:
            return ValidationOutcome(
                final_text=original,
                keep_original=True,
                reasons=critical_reasons,
                signals=signals,
            )
        edits = extract_edits(original, candidate)
        accepted: list[Edit] = []
        rejected: list[Edit] = []
        protected_spans = extract_protected_spans(original)
        for edit in edits:
            edit_reasons: list[str] = []
            for span in protected_spans:
                if not (edit.original_end <= span.start or edit.original_start >= span.end):
                    if edit.original_text != edit.replacement_text:
                        edit_reasons.append("protected_span_overlap")
            if not edit_reasons and self._is_safe_lexical_edit(original, edit):
                accepted.append(edit)
            else:
                if not edit_reasons:
                    edit_reasons.append("unsafe_lexical_edit")
                rejected.append(edit)
        if not accepted:
            return ValidationOutcome(
                final_text=original,
                keep_original=True,
                rejected_edits=edits,
                reasons=["no_safe_edits"],
                signals=signals,
            )
        from grammar.edit_extractor import apply_edits

        final_text = apply_edits(original, accepted)
        if final_text == original:
            return ValidationOutcome(
                final_text=original,
                keep_original=True,
                accepted_edits=[],
                rejected_edits=edits,
                reasons=reasons or ["no_effective_change"],
                signals=signals,
            )
        return ValidationOutcome(
            accepted_edits=accepted,
            rejected_edits=rejected,
            final_text=final_text,
            keep_original=False,
            reasons=reasons,
            signals=signals,
        )
