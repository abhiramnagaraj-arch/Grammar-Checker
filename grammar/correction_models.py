from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Decision = Literal["AUTO_APPLY", "SUGGEST", "KEEP_ORIGINAL"]
Source = Literal["LANGUAGETOOL", "QWEN", "ORIGINAL", "UNAVAILABLE"]
Action = Literal["auto_apply", "suggest", "qwen", "ignore"]
ConfidenceLevel = Literal["high", "medium", "low"]


@dataclass(slots=True)
class LanguageToolFinding:
    rule_id: str
    category_id: str
    issue_type: str
    message: str
    offset: int
    length: int
    replacements: list[str] = field(default_factory=list)
    confidence_level: ConfidenceLevel = "medium"
    action: Action = "suggest"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.offset + self.length

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["end"] = self.end
        return data


@dataclass(slots=True)
class Edit:
    operation: Literal["insert", "delete", "replace"]
    original_text: str
    replacement_text: str
    original_start: int
    original_end: int
    candidate_start: int
    candidate_end: int
    source: Source = "ORIGINAL"
    rule_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationSignals:
    errors_before: int = 0
    errors_after: int = 0
    target_findings_removed: bool = False
    new_findings_introduced: bool = False
    character_edit_ratio: float = 0.0
    changed_word_ratio: float = 0.0
    length_ratio: float = 1.0
    protected_content_preserved: bool = True
    numbers_preserved: bool = True
    negation_preserved: bool = True
    tense_approximately_preserved: bool = True
    semantic_similarity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CorrectionSuggestion:
    original_text: str
    suggested_text: str
    message: str
    rule_id: str
    confidence_level: ConfidenceLevel
    start: int
    end: int
    replacements: list[str] = field(default_factory=list)
    source: Source = "LANGUAGETOOL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CorrectionResult:
    original_text: str
    final_text: str
    decision: Decision
    source: Source
    changed: bool
    suggestions: list[CorrectionSuggestion] = field(default_factory=list)
    accepted_edits: list[Edit] = field(default_factory=list)
    rejected_edits: list[Edit] = field(default_factory=list)
    validation: ValidationSignals = field(default_factory=ValidationSignals)
    reasons: list[str] = field(default_factory=list)
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "final_text": self.final_text,
            "decision": self.decision,
            "source": self.source,
            "changed": self.changed,
            "suggestions": [item.to_dict() for item in self.suggestions],
            "accepted_edits": [item.to_dict() for item in self.accepted_edits],
            "rejected_edits": [item.to_dict() for item in self.rejected_edits],
            "validation": self.validation.to_dict(),
            "reasons": list(self.reasons),
            "request_id": self.request_id,
        }

