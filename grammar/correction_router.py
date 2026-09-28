from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

from grammar.config import AppConfig, load_app_config
from grammar.correction_models import CorrectionResult, CorrectionSuggestion, Edit
from grammar.correction_validator import CorrectionValidator
from grammar.languagetool_client import LanguageToolClient, LanguageToolUnavailable
from grammar.languagetool_classifier import ClassifiedFindings, classify_matches
from grammar.protected_content import is_skippable_email_like_text
from grammar.qwen_corrector import QwenCorrector


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineMetrics:
    sentences_checked: int = 0
    sentences_kept_original: int = 0
    languagetool_auto_applied: int = 0
    languagetool_suggestions: int = 0
    qwen_calls: int = 0
    qwen_candidates_accepted: int = 0
    qwen_candidates_rejected: int = 0
    protected_content_rejections: int = 0
    negation_change_rejections: int = 0
    number_change_rejections: int = 0
    new_error_rejections: int = 0
    large_edit_rejections: int = 0
    languagetool_failures: int = 0
    total_processing_seconds: float = 0.0

    def record_latency(self, seconds: float) -> None:
        self.total_processing_seconds += seconds

    def average_processing_time(self) -> float:
        if self.sentences_checked == 0:
            return 0.0
        return self.total_processing_seconds / self.sentences_checked


class CorrectionRouter:
    def __init__(
        self,
        config: AppConfig | None = None,
        lt_client: LanguageToolClient | None = None,
        qwen_corrector: QwenCorrector | None = None,
        validator: CorrectionValidator | None = None,
        metrics: PipelineMetrics | None = None,
        qwen_threads: int = 8,
    ) -> None:
        self.config = config or load_app_config()
        self.lt_client = lt_client or LanguageToolClient(self.config.languagetool)
        self.qwen_corrector = qwen_corrector
        self.validator = validator or CorrectionValidator(self.config.validation)
        self.metrics = metrics or PipelineMetrics()
        self.qwen_threads = qwen_threads
        self.ngram_enabled = bool(self.config.languagetool.ngrams_path)

    def _request_id(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def _lt_analysis(self, text: str) -> tuple[ClassifiedFindings | None, list[str]]:
        if not self.config.languagetool.enabled:
            return None, ["languagetool_disabled"]
        try:
            response = self.lt_client.check(text)
            classified = classify_matches(response.matches, self.config.routing)
            return classified, []
        except (LanguageToolUnavailable, Exception) as error:
            self.metrics.languagetool_failures += 1
            return None, [f"languagetool_unavailable:{error}"]

    def _lt_counts(self, text: str) -> tuple[int | None, ClassifiedFindings | None]:
        classified, _ = self._lt_analysis(text)
        if classified is None:
            return None, None
        return classified.serious_count, classified

    def _apply_single_lt_finding(self, original: str, finding) -> str:
        if not finding.replacements:
            return original
        replacement = finding.replacements[0]
        return original[: finding.offset] + replacement + original[finding.end :]

    def _decision_keep(self, original: str, reasons: list[str], request_id: str, source: str = "ORIGINAL") -> CorrectionResult:
        self.metrics.sentences_kept_original += 1
        return CorrectionResult(
            original_text=original,
            final_text=original,
            decision="KEEP_ORIGINAL",
            source=source,  # type: ignore[arg-type]
            changed=False,
            reasons=reasons,
            request_id=request_id,
        )

    def _log_result(
        self,
        request_id: str,
        result: CorrectionResult,
        lt_available: bool,
        lt_count: int | None,
        qwen_called: bool,
        started: float,
    ) -> CorrectionResult:
        elapsed = time.perf_counter() - started
        self.metrics.record_latency(elapsed)
        LOGGER.info(
            "hybrid_correction",
            extra={
                "request_id": request_id,
                "decision": result.decision,
                "source": result.source,
                "changed": result.changed,
                "lt_available": lt_available,
                "lt_finding_count": lt_count,
                "qwen_called": qwen_called,
                "accepted_edits": len(result.accepted_edits),
                "rejected_edits": len(result.rejected_edits),
                "latency_seconds": round(elapsed, 4),
                "ngram_enabled": self.ngram_enabled,
            },
        )
        return result

    def _suggestions_from_findings(self, findings) -> list[CorrectionSuggestion]:
        suggestions: list[CorrectionSuggestion] = []
        for finding in findings:
            suggestions.append(
                CorrectionSuggestion(
                    original_text="",
                    suggested_text=finding.replacements[0] if finding.replacements else "",
                    message=finding.message,
                    rule_id=finding.rule_id,
                    confidence_level=finding.confidence_level,
                    start=finding.offset,
                    end=finding.end,
                    replacements=list(finding.replacements),
                )
            )
        return suggestions

    def correct(self, text: str) -> CorrectionResult:
        request_id = self._request_id(text)
        started = time.perf_counter()
        self.metrics.sentences_checked += 1

        if not text.strip():
            result = self._decision_keep(text, ["empty_input"], request_id)
            return self._log_result(request_id, result, False, None, False, started)

        if is_skippable_email_like_text(text):
            result = self._decision_keep(text, ["skippable_email_like_text"], request_id)
            return self._log_result(request_id, result, False, None, False, started)

        classified, lt_reasons = self._lt_analysis(text)
        if classified is None:
            if self.config.allow_model_only_mode and self.qwen_corrector is not None:
                # Explicit opt-in only. The default remains original-as-fallback.
                return self._qwen_route(text, request_id, lt_reasons, model_only=True, started=started)
            result = self._decision_keep(text, lt_reasons or ["languagetool_unavailable"], request_id, source="UNAVAILABLE")
            return self._log_result(request_id, result, False, None, False, started)

        if not classified.objective_findings:
            result = self._decision_keep(text, ["no_objective_findings"], request_id)
            return self._log_result(request_id, result, True, classified.serious_count, False, started)

        if classified.route == "auto_apply" and classified.auto_apply_finding is not None:
            candidate = self._apply_single_lt_finding(text, classified.auto_apply_finding)
            before_count, _ = self._lt_counts(text)
            after_count, after_classified = self._lt_counts(candidate)
            if before_count is None or after_count is None:
                self.metrics.languagetool_failures += 1
                result = self._decision_keep(text, ["languagetool_recheck_unavailable"], request_id)
                return self._log_result(request_id, result, True, classified.serious_count, False, started)
            validation = self.validator.apply_and_validate_edits(
                text,
                candidate,
                errors_before=before_count,
                errors_after=after_count,
                lt_findings=classified.objective_findings,
            )
            if validation.keep_original:
                self.metrics.large_edit_rejections += 1
                result = self._decision_keep(text, validation.reasons or ["lt_recheck_failed"], request_id)
                result.validation = validation.signals
                return self._log_result(request_id, result, True, classified.serious_count, False, started)

            if after_classified is not None and after_classified.serious_count > before_count:
                self.metrics.new_error_rejections += 1
                result = self._decision_keep(text, ["new_serious_errors_detected"], request_id)
                result.validation = validation.signals
                return self._log_result(request_id, result, True, classified.serious_count, False, started)

            result = CorrectionResult(
                original_text=text,
                final_text=validation.final_text,
                decision="AUTO_APPLY",
                source="LANGUAGETOOL",
                changed=validation.final_text != text,
                suggestions=[],
                accepted_edits=[
                    Edit(
                        operation="replace",
                        original_text=text[classified.auto_apply_finding.offset:classified.auto_apply_finding.end],
                        replacement_text=classified.auto_apply_finding.replacements[0],
                        original_start=classified.auto_apply_finding.offset,
                        original_end=classified.auto_apply_finding.end,
                        candidate_start=0,
                        candidate_end=0,
                        source="LANGUAGETOOL",
                        rule_id=classified.auto_apply_finding.rule_id,
                    )
                ],
                rejected_edits=[],
                validation=validation.signals,
                request_id=request_id,
            )
            self.metrics.languagetool_auto_applied += 1
            return self._log_result(request_id, result, True, classified.serious_count, False, started)

        if classified.route == "suggest":
            suggestions = self._suggestions_from_findings(classified.suggestions or classified.objective_findings)
            self.metrics.languagetool_suggestions += 1
            result = CorrectionResult(
                original_text=text,
                final_text=text,
                decision="SUGGEST",
                source="LANGUAGETOOL",
                changed=False,
                suggestions=suggestions,
                request_id=request_id,
            )
            return self._log_result(request_id, result, True, classified.serious_count, False, started)

        if self.qwen_corrector is None:
            self.qwen_corrector = QwenCorrector(self.config.qwen_model_name, threads=self.qwen_threads)
        result = self._qwen_route(text, request_id, lt_reasons, started=started)
        return result

    def _qwen_route(
        self,
        text: str,
        request_id: str,
        reasons: list[str],
        model_only: bool = False,
        started: float | None = None,
    ) -> CorrectionResult:
        self.metrics.qwen_calls += 1
        candidate_bundle = self.qwen_corrector.generate_candidate(text)  # type: ignore[union-attr]
        candidate = candidate_bundle.candidate
        before_count, before_classified = self._lt_counts(text)
        after_count, after_classified = self._lt_counts(candidate)
        if before_count is None or after_count is None:
            self.metrics.languagetool_failures += 1
            result = CorrectionResult(
                original_text=text,
                final_text=text,
                decision="KEEP_ORIGINAL",
                source="ORIGINAL",
                changed=False,
                suggestions=[],
                validation=self.validator.validate_candidate(text, text),
                reasons=["languagetool_recheck_unavailable"],
                request_id=request_id,
            )
            if started is not None:
                return self._log_result(request_id, result, before_count is not None, before_count, True, started)
            return result
        validation = self.validator.apply_and_validate_edits(
            text,
            candidate,
            errors_before=before_count,
            errors_after=after_count,
            lt_findings=before_classified.objective_findings if before_classified else None,
        )

        if after_classified is not None and after_classified.serious_count > before_count:
            validation.keep_original = True
            validation.reasons.append("new_serious_errors_detected")

        if validation.keep_original:
            self.metrics.qwen_candidates_rejected += 1
            if candidate != text and not model_only:
                result = CorrectionResult(
                    original_text=text,
                    final_text=text,
                    decision="SUGGEST",
                    source="QWEN",
                    changed=False,
                    suggestions=[
                        CorrectionSuggestion(
                            original_text=text,
                            suggested_text=candidate,
                            message="Qwen candidate requires manual review",
                            rule_id="QWEN_CANDIDATE",
                            confidence_level="medium",
                            start=0,
                            end=len(text),
                            source="QWEN",
                        )
                    ],
                    rejected_edits=validation.rejected_edits,
                    validation=validation.signals,
                    reasons=validation.reasons or reasons,
                    request_id=request_id,
                )
                if started is not None:
                    self.metrics.record_latency(time.perf_counter() - started)
                return result
            result = CorrectionResult(
                original_text=text,
                final_text=text,
                decision="KEEP_ORIGINAL" if not model_only else "SUGGEST",
                source="QWEN" if model_only else "ORIGINAL",
                changed=False,
                suggestions=[],
                rejected_edits=validation.rejected_edits,
                validation=validation.signals,
                reasons=validation.reasons or reasons,
                request_id=request_id,
            )
            if started is not None:
                return self._log_result(request_id, result, before_count is not None, before_count, True, started)
            return result

        if not validation.accepted_edits and candidate != text:
            self.metrics.qwen_candidates_rejected += 1
            result = CorrectionResult(
                original_text=text,
                final_text=text,
                decision="SUGGEST",
                source="QWEN",
                changed=False,
                suggestions=[
                    CorrectionSuggestion(
                        original_text=text,
                        suggested_text=candidate,
                        message="Qwen candidate requires manual review",
                        rule_id="QWEN_CANDIDATE",
                        confidence_level="medium",
                        start=0,
                        end=len(text),
                        source="QWEN",
                    )
                ],
                rejected_edits=validation.rejected_edits,
                validation=validation.signals,
                reasons=validation.reasons or reasons,
                request_id=request_id,
            )
            if started is not None:
                self.metrics.record_latency(time.perf_counter() - started)
            return result

        final_text = validation.final_text
        accepted = validation.accepted_edits
        result = CorrectionResult(
            original_text=text,
            final_text=final_text,
            decision="AUTO_APPLY",
            source="QWEN",
            changed=final_text != text,
            suggestions=[],
            accepted_edits=accepted,
            rejected_edits=validation.rejected_edits,
            validation=validation.signals,
            reasons=validation.reasons or reasons,
            request_id=request_id,
        )
        self.metrics.qwen_candidates_accepted += 1
        if started is not None:
            return self._log_result(request_id, result, before_count is not None, before_count, True, started)
        return result
