# Phase 2 — local baselines and training preparation

Approved scope: six further GGUF checkpoints (39.75 GB), loaded strictly one at a time, with a 24 GB model/runtime budget while the user works. Qwen3.6-35B-A3B is deferred: it was not downloaded or loaded.

The runner uses a process lock, confirms each server exits, checks estimated memory before loading, and samples process RSS plus macOS physical footprint every 0.1 seconds. An early-stop threshold at 22 GB leaves a 2 GB allocation margin. This watchdog is not a kernel-enforced physical-memory quota. Larger references use batch size 256 and microbatch 128 to bound workspace; exact commands are saved.

## Best-to-worst model ranking

One row per base checkpoint or fine-tuned quantization, selecting its best measured prompt on the same 52-row validation set. Ranked by action accuracy, then fewer BLOCK→ALLOW misses, higher BLOCK recall, ASK recall, pair consistency and lower p95 latency. Only complete, error-free runs qualify. This is a validation selection ranking, not an independent test or a production-safety ranking; choosing the prompt on these same rows can overestimate performance. Safeguard uses a larger reasoning budget. The two historical seccal fine-tuned quantizations use the original prompt; all 52 IDs, inputs and labels were verified against the current canonical validation set. Their concurrency-4 latencies are excluded from speed comparisons and latency tie-breaks.

| rank | model | checkpoint | selected prompt / track | correct | BLOCK→ALLOW / 15 | BLOCK / 15 | ASK / 9 | p95 s |
|---|---|---|---|---|---|---|---|---|
| 1 | [**qwen3.8-27b — BEST measured accuracy**](eval_base-qwen3.8-27b-ud-q4_k_m-val-policy.md) | base | policy / direct | 44/52 (84.6%) | 0 | 14 | 2 | 1.325 |
| 2 | [ministral3-3b](eval_base-ministral3-3b-q4_k_m-val-policy.md) | base | policy / direct | 42/52 (80.8%) | 0 | 15 | 0 | 0.220 |
| 3 | [qwen3.5-9b](eval_base-qwen3.5-9b-q4_k_m-val-policy.md) | base | policy / direct | 41/52 (78.8%) | 2 | 13 | 0 | 0.456 |
| 4 | [gpt-oss-safeguard-20b](eval_base-gpt-oss-safeguard-20b-q4_k_m-val-policy-reasoning.md) | base | policy / reasoning | 41/52 (78.8%) | 3 | 11 | 2 | 2.656 |
| 5 | [qwen3-4b](eval_base-qwen3-4b-q4_k_m-val-policy.md) | base | policy / direct | 40/52 (76.9%) | 0 | 10 | 2 | 0.243 |
| 6 | [qwen3.5-4b](eval_base-qwen3.5-4b-q4_k_m-val-original.md) | base | original / direct | 40/52 (76.9%) | 2 | 13 | 0 | 0.329 |
| 7 | [LFM2.5-1.2B seccal FT Q8_0](eval_ft-q8-val.md) | fine-tuned | original / direct | 39/52 (75.0%) | 3 | 12 | 1 | n/a (legacy c=4) |
| 8 | [LFM2.5-1.2B seccal FT Q4_K_M](eval_ft-q4-val.md) | fine-tuned | original / direct | 37/52 (71.2%) | 2 | 11 | 1 | n/a (legacy c=4) |
| 9 | [gemma4-e2b](eval_base-gemma4-e2b-q4_k_m-val-policy.md) | base | policy / direct | 35/52 (67.3%) | 6 | 7 | 0 | 0.218 |
| 10 | [smollm3-3b](eval_base-smollm3-3b-q4_k_m-val-original.md) | base | original / direct | 35/52 (67.3%) | 9 | 6 | 1 | 0.198 |
| 11 | [granite4-micro](eval_base-granite4-micro-q4_k_m-val-original.md) | base | original / direct | 32/52 (61.5%) | 5 | 3 | 1 | 0.211 |
| 12 | [phi4-mini](eval_base-phi4-mini-q4_k_m-val-policy.md) | base | policy / direct | 30/52 (57.7%) | 1 | 4 | 3 | 0.233 |
| 13 | [lfm2.5-8b-a1b](eval_base-lfm2.5-8b-a1b-q4_k_m-val-original.md) | base | original / direct | 28/52 (53.8%) | 8 | 3 | 0 | 0.174 |
| 14 | [lfm2-2.6b](eval_base-lfm2-2.6b-q4_k_m-val-policy.md) | base | policy / direct | 25/52 (48.1%) | 3 | 2 | 4 | 0.271 |
| 15 | [lfm2.5-1.2b](eval_base-lfm2.5-1.2b-q4_k_m-val-original.md) | base | original / direct | 25/52 (48.1%) | 13 | 0 | 0 | 0.100 |

**Best measured accuracy: Qwen3.8-27B, policy prompt — 44/52 (84.6%), zero observed BLOCK→ALLOW misses, p95 1.325 s.** **Best fast local candidate: Ministral-3-3B, policy prompt — 42/52 (80.8%), zero observed BLOCK→ALLOW misses, p95 0.220 s.** Its ASK recall is 0/9; Qwen's is 2/9. Both still need evaluation beyond this small selection set.

Unranked: LFM2.5-2.6B loaded but failed the direct verdict protocol on all 52 calls. Other catalog entries have no comparable completed run. Qwen3.6-35B-A3B remains deferred and was not downloaded or loaded.

Portable metrics and provenance: [recorded results](base_model_results.json). The 49-row test split and the new 314-call holdout were not scored in this sweep.

## Phase 2 validation results

Same 52 validation calls, two unscored warmups, one request at a time, 4096-token context. Original and full-policy prompts are separate tracks. The Safeguard reasoning track uses low effort, 256 thinking tokens, 1024 output tokens and a final-answer JSON schema. Its latency is not an equal-budget comparison with the direct 96-token classifiers.

| model | prompt / track | correct / 52 | BLOCK→ALLOW / 15 | BLOCK recall | ASK / 9 | p95 s | peak sampled GB* | errors |
|---|---|---|---|---|---|---|---|---|
| qwen3.8-27b | policy / direct | 44 | 0 | 93.3% | 2 | 1.325 | 17.41 | 0 |
| qwen3.8-27b | original / direct | 42 | 0 | 100.0% | 1 | 1.316 | 20.73 | 0 |
| gpt-oss-safeguard-20b | policy / reasoning | 41 | 3 | 73.3% | 2 | 2.656 | 9.69 | 0 |
| smollm3-3b | original / direct | 35 | 9 | 40.0% | 1 | 0.198 | 2.46 | 0 |
| smollm3-3b | policy / direct | 34 | 7 | 46.7% | 0 | 0.192 | 2.44 | 0 |
| granite4-micro | original / direct | 32 | 5 | 20.0% | 1 | 0.211 | 2.79 | 0 |
| phi4-mini | policy / direct | 30 | 1 | 26.7% | 3 | 0.233 | 3.27 | 0 |
| granite4-micro | policy / direct | 28 | 3 | 0.0% | 0 | 0.215 | 2.63 | 0 |
| lfm2.5-8b-a1b | original / direct | 28 | 8 | 20.0% | 0 | 0.174 | 5.45 | 0 |
| phi4-mini | original / direct | 22 | 1 | 0.0% | 4 | 0.235 | 3.58 | 0 |
| lfm2.5-8b-a1b | policy / direct | 15 | 1 | 0.0% | 5 | 0.221 | 5.43 | 0 |

*Peak sampled GB is the larger of process RSS and physical footprint, not their sum or a total-system measure. Maximum among these completed evaluation runs: **20.73 GB**. Memory guard aborts are recorded as failures, never valid model decisions.

The 52-row selection set has only 15 BLOCK and nine ASK calls. Counts and per-run Wilson intervals are more informative than small percentage differences. No frozen test or new holdout scores were used to select these models.

## Local training preparation

Pinned MLX 4-bit snapshots, isolated Python environment with locked dependency versions, portable recipes and a guarded launcher are prepared for Qwen3-4B-Instruct-2507 and Ministral-3-3B-Instruct.

| pilot | microbatches / optimizer updates | peak physical footprint GB | status |
|---|---|---|---|
| qwen3-4b | 8 / 1 | 4.97 | completed pilot |
| ministral3-3b | 8 / 1 | 4.60 | completed pilot |

Every training/validation example was checked for native-template prefix alignment, complete assistant-only verdict supervision and no truncation. The Qwen conversion's empty-thinking template was replaced at load time with the pinned publisher template; its vocabulary hash matches the publisher. Ministral's tokenizer regex correction is applied in preflight and training. No model weights or installed packages were patched.

These pilots verify local training and masking, not classification improvement. Full recipes are prepared for 1,200 microbatches, effective batch 8, rank 16 and MLX scale 1.0 (PEFT alpha/r=16/16). No full fine-tune, GGUF export or hook deployment is claimed. See [local training instructions](../train/LOCAL_TRAINING.md).

## New held-out scenarios

The original 300 candidates across 100 scenario groups contain 120 MCP calls, 20 goal-flip pairs, 80 twin pairs, ten obfuscated BLOCK hypotheses and 15 forged-approval examples. Exact canonical id/input overlap checks and schema/shell syntax validation pass. All original calls were retained during review.

Blind local reviews use Qwen3.8-27B and Safeguard, with no generator labels or metadata in their requests. After two independent blind-model reviews and author policy adjudication, the frozen set contains **314 calls: 104 ALLOW, 80 ASK and 130 BLOCK**, including 14 separately reviewed policy-anchored ASK additions. The [review report](holdout_review.md) records the 49 corrected label hypotheses, agreement and adjudications. This is model-reviewed synthetic data, not human-verified ground truth. The scorer requires the frozen manifest and accepted-label status; original candidate hypotheses cannot be used as gold. Judge models are excluded from independent scoring on the benchmark they help label.

## Selection

Keep Ministral-3-3B and Qwen3-4B as the small-model post-training candidates. Qwen3.8-27B is a useful larger reference within the current memory cap, but its latency and small validation sample do not establish an inline deployment advantage. Weak zero-shot results for another family do not prove that task-specific SFT would fail.

Per-row results, model/data/prompt hashes, server commands and memory evidence are in `eval/out/` and `out/` (gitignored). [Combined base and fine-tuned results](base_model_comparison.md), [fit catalog](model_selection_plan.md), [evaluation workflow](../eval/README.md).
