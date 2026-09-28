import unittest

from grammar.edit_extractor import apply_edits, extract_edits


class EditExtractorTests(unittest.TestCase):
    def test_extract_edits_preserves_local_changes(self) -> None:
        original = "She have finished report and forwarded it to Ravi."
        candidate = "She has finished the report and sent it to Ravi."

        edits = extract_edits(original, candidate)

        self.assertTrue(
            any(
                edit.original_text.strip() == "have"
                and edit.replacement_text.strip() == "has"
                for edit in edits
            )
        )
        self.assertTrue(any(edit.replacement_text.strip() == "the" for edit in edits))
        self.assertTrue(any(edit.original_text.strip() == "forwarded" for edit in edits))

    def test_apply_edits_round_trip(self) -> None:
        original = "She have completed the report."
        candidate = "She has completed the report."
        edits = extract_edits(original, candidate)
        self.assertEqual(apply_edits(original, edits), candidate)
