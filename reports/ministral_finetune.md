# Ministral-3-3B local fine-tune

**Completed, not promoted: retain the base checkpoint.** The selected adapter's validation accuracy improved, but holdout accuracy declined from 221/314 (70.4%) to 211/314 (67.2%). ASK recognition fell from 26/80 to 11/80 and false blocks rose from 6/104 to 17/104. Dangerous misses improved slightly, from 18/130 to 16/130. These mixed results do not justify replacing the base. No deployment was changed.

Completed **400 microbatches / 50 optimizer updates** with MLX 4-bit QLoRA on the local Apple GPU. Training used 399 canonical examples and 52 validation examples, the full labeling-policy prompt and assistant-only verdict loss. No historical test or new holdout examples entered training.

Rank 8, MLX scale 1.0, learning rate 2e-05, batch 1, accumulation 8, maximum sequence length 2048, all decoder layers, gradient checkpointing, seed 3407. Training peaked at **4.70 GB** sampled process RSS/physical footprint, under the 24 GB working cap.

The saved Ministral recipe was corrected from 150 microbatches / scale 16 to the documented 1,200 / scale 1 before the initial trial. This conservative follow-up uses its own recorded recipe. Earlier pilot outputs are preserved. Its eight-microbatch, scale-1 pilot passed before training.

## Validation checkpoint selection

Selected the adapter at **400 microbatches** using the 52-row validation set. Highest validation action accuracy, then fewer BLOCK-to-ALLOW misses, higher BLOCK recall, ASK recall, pair consistency, earlier checkpoint. The selection manifest was saved before either model's holdout evaluation. The complete training run and every saved checkpoint remain available.

| checkpoint | correct / 52 | BLOCK→ALLOW / 15 | ASK / 9 |
|---|---|---|---|
| [200](eval_mlx-ministral3-3b-ft-policy-conservative-step200-val.md) | 38 | 3 | 0 |
| [**400 — selected**](eval_mlx-ministral3-3b-ft-policy-conservative-step400-val.md) | 42 | 2 | 2 |

Adapter targets: `self_attn.q_proj`, `self_attn.v_proj`. Learning rate uses the recorded warmup/cosine schedule; schedule steps count optimizer updates.


## Matched evaluation

Both rows for each split use the same pinned MLX 4-bit checkpoint, native tokenizer with the Mistral regex correction, full-policy prompt, greedy decoding constrained to the same 19 canonical schema-valid JSON verdicts, 96-token output limit, strict verdict parser, two unscored warmups and one request at a time. Invalid outputs count as errors and incorrect decisions. The decoder does not see gold labels. The initial unconstrained probe emitted Markdown and extra JSON fields; it is preserved locally and excluded from these classification comparisons. This is a separate serving track from GGUF, with fixed canonical whitespace and field order; differences from that leaderboard cannot be attributed to training alone.

| split | checkpoint | correct | BLOCK→ALLOW | BLOCK recall | ASK recall | false BLOCK | pairs | errors | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| val | [base](eval_mlx-ministral3-3b-base-policy-val.md) | 38/52 (73.1%) | 1/15 | 12/15 | 0/9 | 2/28 | 4/10 | 0 | 0.405 |
| holdout | [base](eval_mlx-ministral3-3b-base-policy-holdout.md) | 221/314 (70.4%) | 18/130 | 105/130 | 26/80 | 6/104 | 73/100 | 0 | 0.664 |
| val | [fine-tuned](eval_mlx-ministral3-3b-ft-policy-conservative-val.md) | 42/52 (80.8%) | 2/15 | 13/15 | 2/9 | 1/28 | 6/10 | 0 | 0.905 |
| holdout | [fine-tuned](eval_mlx-ministral3-3b-ft-policy-conservative-holdout.md) | 211/314 (67.2%) | 16/130 | 114/130 | 11/80 | 17/104 | 77/100 | 0 | 0.593 |

Each linked report includes Wilson uncertainty intervals and misjudged IDs. The 314-call frozen holdout contains 104 ALLOW, 80 ASK and 130 BLOCK calls. It is model-reviewed, author-adjudicated synthetic data, not human-verified ground truth. Recipe and final-checkpoint choices were fixed before scoring it. Do not tune this model against these holdout outcomes. The historical 49-row test set remains untouched in this phase.

## Artifacts and reproduction

The selected adapter is saved locally at `out/mlx-ministral3-3b-policy-conservative-step400/adapters.safetensors`. Its configuration is in the same directory; the effective recipe, every checkpoint, training log and memory evidence are under `out/mlx-ministral3-3b-policy-conservative`. It requires the pinned MLX base weights; it is not a standalone GGUF. No hook or deployment was changed.

Adapter SHA-256: `dd98ce075ecb4aa6e7781f390e890b7d4ea54bcf948342524b6e8edcc2ea2f15`. [Portable metrics and training evidence](ministral_finetune_results.json) are committed; weights and raw logs remain local. See [training and evaluation commands](../train/LOCAL_TRAINING.md). Regenerate this report with `python3 eval/report_mlx_training.py`; a fresh checkout can use the recorded snapshot without loading a model.

## Earlier trial — preserved, not promoted

The initial all-linear, rank-16, constant-learning-rate 2e-4 run completed 1,200 microbatches / 150 updates. It regressed against the matched base's 38/52 validation accuracy. Its checkpoints scored:

| microbatches | correct / 52 | BLOCK→ALLOW / 15 | ASK / 9 |
|---|---|---|---|
| [400](eval_mlx-ministral3-3b-ft-policy-step400-val.md) | 15 | 0 | 0 |
| [800](eval_mlx-ministral3-3b-ft-policy-step800-val.md) | 29 | 14 | 0 |
| [1200](eval_mlx-ministral3-3b-ft-policy-step1200-val.md) | 27 | 14 | 0 |

No holdout outcomes were released for that trial. The conservative recipe was chosen using training/validation evidence only, before any holdout score. Earlier adapters, checkpoints and logs remain preserved.
