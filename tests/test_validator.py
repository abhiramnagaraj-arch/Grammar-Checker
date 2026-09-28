import unittest

from grammar.config import ValidationThresholds
from grammar.correction_validator import CorrectionValidator


class ValidatorTests(unittest.TestCase):
    def test_validator_rejects_number_change(self) -> None:
        validator = CorrectionValidator(ValidationThresholds())
        reasons = validator.hard_reject(
            "The meeting is scheduled for 5 PM.",
            "The meeting was scheduled for 6 PM.",
        )

        self.assertTrue(any(reason.startswith("protected_") for reason in reasons))

    def test_validator_rejects_negation_change(self) -> None:
        validator = CorrectionValidator(ValidationThresholds())
        reasons = validator.hard_reject(
            "Ravi did not approve the request.",
            "Ravi approved the request.",
        )

        self.assertTrue(
            "negation_changed" in reasons
            or any(reason.startswith("protected_") for reason in reasons)
        )

    def test_validator_rejects_paraphrase(self) -> None:
        validator = CorrectionValidator(ValidationThresholds())
        reasons = validator.hard_reject(
            "Please send the report today.",
            "Kindly submit the document today.",
        )

        self.assertTrue(
            "changed_word_ratio_exceeded" in reasons
            or "character_edit_ratio_exceeded" in reasons
        )
