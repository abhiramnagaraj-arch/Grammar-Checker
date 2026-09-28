from dataclasses import dataclass
import unittest

from grammar.config import AppConfig, LanguageToolSettings, RoutingPolicy, ValidationThresholds
from grammar.correction_router import CorrectionRouter
from grammar.correction_validator import CorrectionValidator


@dataclass
class DummyResponse:
    matches: list[dict]


class DummyLTClient:
    def __init__(self, responses: dict[str, DummyResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def check(self, text: str) -> DummyResponse:
        self.calls.append(text)
        if text not in self.responses:
            return DummyResponse(matches=[])
        return self.responses[text]


class DummyQwenCorrector:
    def __init__(self, candidate: str) -> None:
        self.candidate = candidate
        self.calls: list[str] = []

    def generate_candidate(self, text: str):
        self.calls.append(text)
        return type("QwenCandidate", (), {"candidate": self.candidate, "prompt": ""})()


def make_match(rule_id: str, issue_type: str, offset: int, length: int, replacements: list[str]) -> dict:
    return {
        "rule": {
            "id": rule_id,
            "category": {"id": "GRAMMAR"},
        },
        "issueType": issue_type,
        "message": rule_id,
        "offset": offset,
        "length": length,
        "replacements": [{"value": value} for value in replacements],
    }


def make_router(
    responses: dict[str, DummyResponse],
    candidate: str | None = None,
) -> tuple[CorrectionRouter, DummyLTClient, DummyQwenCorrector | None]:
    config = AppConfig(
        languagetool=LanguageToolSettings(enabled=True),
        validation=ValidationThresholds(),
        routing=RoutingPolicy(),
        models={"qwen": {"architecture": "decoder-only"}},
    )
    lt_client = DummyLTClient(responses)
    qwen = DummyQwenCorrector(candidate) if candidate is not None else None
    router = CorrectionRouter(
        config=config,
        lt_client=lt_client,
        qwen_corrector=qwen,
        validator=CorrectionValidator(config.validation),
        qwen_threads=1,
    )
    return router, lt_client, qwen


class RouterTests(unittest.TestCase):
    def test_keep_original_when_no_objective_findings(self) -> None:
        router, lt_client, qwen = make_router(
            {"Please send the report to Ravi by 5 PM.": DummyResponse(matches=[])}
        )
        result = router.correct("Please send the report to Ravi by 5 PM.")

        self.assertEqual(result.decision, "KEEP_ORIGINAL")
        self.assertEqual(result.final_text, "Please send the report to Ravi by 5 PM.")
        self.assertTrue(qwen is None or not qwen.calls)
        self.assertEqual(lt_client.calls, ["Please send the report to Ravi by 5 PM."])

    def test_auto_apply_single_lt_correction(self) -> None:
        original = "She have completed the report."
        candidate = "She has completed the report."
        router, lt_client, qwen = make_router(
            {
                original: DummyResponse(
                    matches=[
                        make_match("SVA", "grammar", original.index("have"), 4, ["has"])
                    ]
                ),
                candidate: DummyResponse(matches=[]),
            }
        )

        result = router.correct(original)

        self.assertEqual(result.decision, "AUTO_APPLY")
        self.assertEqual(result.final_text, candidate)
        self.assertTrue(qwen is None or not qwen.calls)
        self.assertGreaterEqual(len(lt_client.calls), 2)
        self.assertEqual(lt_client.calls[0], original)

    def test_repeated_word_auto_apply(self) -> None:
        original = "The the server is running."
        candidate = "The server is running."
        router, _, _ = make_router(
            {
                original: DummyResponse(
                    matches=[
                        make_match("ENGLISH_WORD_REPEAT_RULE", "grammar", 0, 7, ["The"])
                    ]
                ),
                candidate: DummyResponse(matches=[]),
            }
        )

        result = router.correct(original)

        self.assertEqual(result.decision, "AUTO_APPLY")
        self.assertEqual(result.final_text, candidate)

    def test_complex_qwen_candidate_accepts_only_safe_edits(self) -> None:
        original = "She have finished report and forwarded it to Ravi."
        candidate = "She has finished the report and sent it to Ravi."
        router, _, qwen = make_router(
            {
                original: DummyResponse(
                    matches=[
                        make_match("SVA", "grammar", original.index("have"), 4, ["has"])
                        ,
                        make_match("BROKEN_VERB", "grammar", original.index("forwarded"), 9, [])
                    ]
                ),
                candidate: DummyResponse(matches=[]),
            },
            candidate=candidate,
        )

        result = router.correct(original)

        self.assertIsNotNone(qwen)
        self.assertEqual(qwen.calls, [original])
        self.assertEqual(result.decision, "AUTO_APPLY")
        self.assertEqual(result.final_text, "She has finished the report and forwarded it to Ravi.")
        self.assertTrue(
            any(
                edit.original_text.strip() == "have"
                and edit.replacement_text.strip() == "has"
                for edit in result.accepted_edits
            )
        )
        self.assertTrue(any(edit.original_text.strip() == "forwarded" for edit in result.rejected_edits))

    def test_unsafe_number_change_rejected(self) -> None:
        original = "The meeting is scheduled for 5 PM."
        candidate = "The meeting was scheduled for 6 PM."
        router, _, _ = make_router({}, candidate=candidate)

        validation = router.validator.apply_and_validate_edits(original, candidate)

        self.assertTrue(validation.keep_original)
        self.assertTrue(any(reason.startswith("protected_") for reason in validation.reasons))

    def test_unsafe_negation_change_rejected(self) -> None:
        original = "Ravi did not approve the request."
        candidate = "Ravi approved the request."
        router, _, _ = make_router({}, candidate=candidate)

        validation = router.validator.apply_and_validate_edits(original, candidate)

        self.assertTrue(validation.keep_original)
        self.assertTrue(
            "negation_changed" in validation.reasons
            or any(reason.startswith("protected_") for reason in validation.reasons)
        )

    def test_languagetool_unavailable_keeps_original(self) -> None:
        class FailingLTClient:
            def check(self, text: str):
                raise RuntimeError("offline")

        config = AppConfig(
            languagetool=LanguageToolSettings(enabled=True),
            validation=ValidationThresholds(),
            routing=RoutingPolicy(),
            models={"qwen": {"architecture": "decoder-only"}},
        )
        router = CorrectionRouter(
            config=config,
            lt_client=FailingLTClient(),
            qwen_corrector=None,
            validator=CorrectionValidator(config.validation),
            qwen_threads=1,
        )

        result = router.correct("Please send the report to Ravi by 5 PM.")

        self.assertEqual(result.decision, "KEEP_ORIGINAL")
        self.assertEqual(result.final_text, "Please send the report to Ravi by 5 PM.")
