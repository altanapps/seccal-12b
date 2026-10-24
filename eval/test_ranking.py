"""Check ranking against the published measurements, without loading models."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rank_models import SNAPSHOT, load_results, ranked_models, validate_historical_rows, latency_text


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = json.loads(SNAPSHOT.read_text())["runs"]

    def test_recorded_winner_and_fast_candidate(self):
        ranked = ranked_models(self.runs)
        self.assertEqual(len(ranked), 15)
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
        self.assertEqual(len(restored), 28)
        self.assertEqual(ranked_models(restored), ranked_models(self.runs))

    def test_historical_quantizations_remain_separate_and_use_val_scores(self):
        ranked = ranked_models(self.runs)
        self.assertEqual(
            [(i + 1, r["name"], r["metrics"]["action_accuracy"]["hits"],
              r["metrics"]["attack_miss"]["hits"]) for i, r in enumerate(ranked)
             if r["provenance"].get("historical")],
            [(7, "ft-q8-val", 39, 3), (8, "ft-q4-val", 37, 2)],
        )
        self.assertEqual(len({r["dataset_sha256"] for r in self.runs}), 1)
        for run in ranked:
            if run["provenance"].get("historical"):
                self.assertEqual(latency_text(run), "n/a (legacy c=4)")

    def test_matching_ids_alone_do_not_establish_same_validation_set(self):
        rows = [{"id": str(i), "split": "val", "gold_action": "ALLOW", "tool_input": {"x": i}}
                for i in range(52)]
        predictions = copy.deepcopy(rows)
        validate_historical_rows(predictions, rows)
        predictions[0]["tool_input"]["x"] = "changed"
        with self.assertRaisesRegex(ValueError, "input/label differs"):
            validate_historical_rows(predictions, rows)

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
