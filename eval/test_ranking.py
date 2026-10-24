"""Check ranking against the published measurements, without loading models."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rank_models import SNAPSHOT, load_results, ranked_models


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = json.loads(SNAPSHOT.read_text())["runs"]

    def test_recorded_winner_and_fast_candidate(self):
        ranked = ranked_models(self.runs)
        self.assertEqual(len(ranked), 13)
        self.assertEqual(
            [(s["provenance"]["model_id"], s["metrics"]["action_accuracy"]["hits"])
             for s in ranked[:2]],
            [("qwen3.8-27b", 44), ("ministral3-3b", 42)],
        )
        self.assertTrue(all(s["metrics"]["error_rate"]["hits"] == 0 for s in ranked))
        self.assertNotIn("lfm2.5-2.6b", [s["provenance"]["model_id"] for s in ranked])

    def test_safety_breaks_equal_accuracy_across_prompts(self):
        ranked = ranked_models(self.runs)
        qwen = next(s for s in ranked if s["provenance"]["model_id"] == "qwen3-4b")
        self.assertEqual(qwen["prompt_mode"], "policy")
        self.assertEqual(qwen["metrics"]["attack_miss"]["hits"], 0)

    def test_snapshot_supports_checkout_without_local_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("rank_models.ROOT", Path(directory)):
                restored = load_results()
        self.assertEqual(len(restored), 26)
        self.assertEqual(ranked_models(restored), ranked_models(self.runs))

    def test_test_split_and_incomplete_or_failed_runs_cannot_win(self):
        winner = ranked_models(self.runs)[0]
        for change in ("test", "incomplete", "failed"):
            invalid = copy.deepcopy(winner)
            invalid["provenance"]["model_id"] = "invalid"
            invalid["metrics"]["action_accuracy"]["value"] = 1
            if change == "test":
                invalid["split"] = "test"
            elif change == "incomplete":
                invalid["rows"] = 51
            else:
                invalid["metrics"]["error_rate"]["hits"] = 1
            self.assertEqual(ranked_models([winner, invalid]), [winner])


if __name__ == "__main__":
    unittest.main()
