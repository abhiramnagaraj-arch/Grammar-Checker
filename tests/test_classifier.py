import unittest

from grammar.config import RoutingPolicy
from grammar.languagetool_classifier import classify_matches


class ClassifierTests(unittest.TestCase):
    def test_classifier_routes_single_high_confidence_as_auto_apply(self) -> None:
        matches = [
            {
                "rule": {"id": "SVA", "category": {"id": "GRAMMAR"}},
                "issueType": "grammar",
                "message": "verb agreement",
                "offset": 4,
                "length": 4,
                "replacements": [{"value": "has"}],
            }
        ]

        classified = classify_matches(matches, RoutingPolicy())

        self.assertEqual(classified.route, "auto_apply")
        self.assertIsNotNone(classified.auto_apply_finding)
