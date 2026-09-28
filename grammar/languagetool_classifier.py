from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from grammar.config import RoutingPolicy
from grammar.correction_models import Action, ConfidenceLevel, LanguageToolFinding
from grammar.protected_content import Span, has_span_overlap


@dataclass(slots=True)
class ClassifiedFindings:
    findings: list[LanguageToolFinding] = field(default_factory=list)
    objective_findings: list[LanguageToolFinding] = field(default_factory=list)
    suggestions: list[LanguageToolFinding] = field(default_factory=list)
    auto_apply_finding: LanguageToolFinding | None = None
    route: Action = "ignore"
    has_overlap: bool = False
    serious_count: int = 0


def _confidence_for(issue_type: str, replacement_count: int, rule_id: str, policy: RoutingPolicy) -> ConfidenceLevel:
    if rule_id in policy.auto_apply_rule_ids:
        return "high"
    if issue_type in policy.high_confidence_issue_types and replacement_count == 1:
        return "high"
    if issue_type in policy.low_confidence_issue_types:
        return "low"
    if replacement_count > 1:
        return "medium"
    return "medium"


def _action_for(finding: LanguageToolFinding, policy: RoutingPolicy) -> Action:
    if finding.rule_id in policy.ignored_rule_ids:
        return "ignore"
    if finding.issue_type in policy.low_confidence_issue_types:
        return "suggest"
    if finding.rule_id in policy.suggest_only_rule_ids:
        return "suggest"
    if finding.rule_id in policy.qwen_route_rule_ids:
        return "qwen"
    if finding.rule_id in policy.auto_apply_rule_ids:
        return "auto_apply"
    if finding.issue_type in policy.high_confidence_issue_types and len(finding.replacements) == 1:
        return "auto_apply"
    if finding.replacements:
        return "suggest"
    return "qwen"


def _parse_finding(raw: dict[str, Any], policy: RoutingPolicy) -> LanguageToolFinding:
    rule = raw.get("rule", {})
    category = rule.get("category", {})
    replacements = [item.get("value", "") for item in raw.get("replacements", []) if item.get("value")]
    finding = LanguageToolFinding(
        rule_id=str(rule.get("id", "")),
        category_id=str(category.get("id", "")),
        issue_type=str(raw.get("issueType", "")),
        message=str(raw.get("message", "")),
        offset=int(raw.get("offset", 0)),
        length=int(raw.get("length", 0)),
        replacements=replacements,
        raw=raw,
    )
    finding.confidence_level = _confidence_for(finding.issue_type, len(replacements), finding.rule_id, policy)
    finding.action = _action_for(finding, policy)
    return finding


def _is_objective(finding: LanguageToolFinding, policy: RoutingPolicy) -> bool:
    return finding.action != "ignore" and finding.issue_type not in policy.low_confidence_issue_types


def classify_matches(raw_matches: list[dict[str, Any]], policy: RoutingPolicy) -> ClassifiedFindings:
    findings = [_parse_finding(match, policy) for match in raw_matches]
    objective = [finding for finding in findings if _is_objective(finding, policy)]
    suggestions = [finding for finding in findings if finding.action == "suggest"]
    spans = [Span(finding.offset, finding.end, finding.rule_id) for finding in objective]
    has_overlap = has_span_overlap(spans)
    serious_count = len(objective)

    auto_candidates = [
        finding
        for finding in objective
        if finding.action == "auto_apply"
        and finding.replacements
        and len(finding.replacements) == 1
    ]

    route: Action = "ignore"
    auto_apply_finding: LanguageToolFinding | None = None

    if not objective:
        route = "ignore"
    elif len(objective) == 1 and auto_candidates and not has_overlap:
        route = "auto_apply"
        auto_apply_finding = auto_candidates[0]
    elif any(finding.action == "qwen" for finding in objective) or has_overlap or len(objective) > 1:
        route = "qwen"
    elif suggestions:
        route = "suggest"
    else:
        route = "qwen"

    return ClassifiedFindings(
        findings=findings,
        objective_findings=objective,
        suggestions=suggestions,
        auto_apply_finding=auto_apply_finding,
        route=route,
        has_overlap=has_overlap,
        serious_count=serious_count,
    )

