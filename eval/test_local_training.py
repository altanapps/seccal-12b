"""Protect the documented local recipe and historical run artifacts."""
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train"))
import run_local
from run_mlx_eval import evaluation_rows, valid_verdicts, VerdictTrie
from run_eval import parse_verdict
from evaluate_ministral_training import select_checkpoint


class LocalTrainingTests(unittest.TestCase):
    def test_conservative_recipe_limits_capacity_and_learning_rate(self):
        config = json.loads((ROOT / "train/recipes/ministral3-3b-policy-conservative.json").read_text())
        self.assertEqual(config["iters"] // config["grad_accumulation_steps"], 50)
        self.assertEqual(config["lora_parameters"]["keys"], ["self_attn.q_proj", "self_attn.v_proj"])
        self.assertEqual(config["lora_parameters"]["rank"], 8)
        self.assertEqual(config["lora_parameters"]["scale"], 1.0)
        self.assertEqual(config["lr_schedule"]["warmup"], 5)
        self.assertEqual(config["lr_schedule"]["arguments"][0], 2e-5)

    def test_verdict_constraints_cover_the_schema_without_gold_or_extra_fields(self):
        verdicts = valid_verdicts()
        self.assertEqual(len(set(verdicts)), 19)
        self.assertEqual(sum(json.loads(text)["action"] == "ALLOW" for text in verdicts), 1)
        self.assertTrue(all(parse_verdict(text)[0] != "PARSE_ERROR" for text in verdicts))
        trie = VerdictTrie([[1, 2, 3], [1, 2, 4]], {9})
        self.assertEqual(trie.allowed([]), [1])
        self.assertEqual(trie.allowed([1, 2]), [3, 4])
        self.assertEqual(trie.allowed([1, 2, 4]), [9])
        self.assertEqual(trie.allowed([1, 2, 4, 9]), [9])
        with self.assertRaises(ValueError):
            trie.allowed([1, 5])

    def test_checkpoint_selection_uses_validation_and_breaks_ties_on_safety(self):
        def candidate(step, misses):
            return {"split": "val", "rows": 52, "dataset_sha256": "same-frozen-data", "checkpoint_microbatches": step,
                    "metrics": {"action_accuracy": {"value": .8}, "attack_miss": {"value": misses},
                                "block_recall": {"value": .9}, "ask_recall": {"value": .2},
                                "pair_consistency": {"value": .5}}}
        early, later, unsafe = candidate(400, 0), candidate(800, 0), candidate(1200, .1)
        self.assertEqual(select_checkpoint([later, unsafe, early]), early)
        early["split"] = "holdout"
        with self.assertRaisesRegex(ValueError, "never holdout"):
            select_checkpoint([early, later])

    def test_recipes_match_the_documented_update_budget_and_lora_scaling(self):
        for name in ("ministral3-3b", "qwen3-4b"):
            config = json.loads((ROOT / f"train/recipes/{name}-policy.json").read_text())
            self.assertEqual(config["iters"], 1200)
            self.assertEqual(config["iters"] // config["grad_accumulation_steps"], 150)
            self.assertEqual(config["iters"] % config["grad_accumulation_steps"], 0)
            self.assertEqual(config["lora_parameters"]["scale"], 1.0)
            self.assertEqual(config["lora_parameters"]["rank"], 16)
            self.assertTrue(config["mask_prompt"])

    def test_existing_training_artifacts_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = root / "train/recipes/ministral3-3b-policy.json"
            recipe.parent.mkdir(parents=True)
            recipe.write_text(json.dumps({"adapter_path": "out/existing"}))
            artifact = root / "out/existing/adapters.safetensors"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("preserve this run")
            original_cwd = Path.cwd()
            try:
                with contextlib.redirect_stdout(io.StringIO()), patch.object(run_local, "ROOT", root), patch.object(run_local, "preflight", return_value={}), \
                     patch.object(sys, "argv", ["run_local.py", "--model", "ministral3-3b"]):
                    with self.assertRaisesRegex(FileExistsError, "preserving existing run"):
                        run_local.main()
            finally:
                import os
                os.chdir(original_cwd)
            self.assertEqual(artifact.read_text(), "preserve this run")

    def test_eval_inputs_are_complete_and_disjoint_from_training(self):
        train = []
        for filename in ("accepted", "adjudicated"):
            train.extend(json.loads(line) for line in
                         (ROOT / f"data/synth/out/{filename}.jsonl").read_text().splitlines() if line)
        train_ids = {row["id"] for row in train if row["split"] == "train"}
        for split, count in (("val", 52), ("holdout", 314)):
            rows = evaluation_rows(split)
            self.assertEqual(len(rows), count)
            self.assertFalse(train_ids.intersection(row["id"] for row in rows))
            self.assertTrue(all(row["split"] == split for row in rows))


if __name__ == "__main__":
    unittest.main()
