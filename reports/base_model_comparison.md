# Local model comparison: base and fine-tuned

Selection set: the existing 52 validation rows (28 ALLOW, 9 ASK, 15 BLOCK; 10 contrast pairs). The frozen 49-row test set has not been run in this sweep. These small samples cannot establish production safety; even 0/15 attack misses has a roughly 20% Wilson upper bound.

New direct runs use one server slot, request concurrency 1, two unscored warmups, temperature 0, the repository verdict grammar, 4096-token context and thinking disabled. Reasoning runs are labeled separately, with low effort, 256 thinking tokens, a 1024-token total output budget and final-answer JSON schema. Original and policy prompts are separate tracks. The policy track appends the existing labeling policy, which is not the prompt used to train iteration 1.

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

## All measured prompt variants

Within each prompt track, successful runs are sorted by the same ranking criteria; protocol failures follow.

| model / prompt | correct | BLOCK recall | BLOCK→ALLOW | ASK recall | ALLOW precision | false BLOCK | pairs | p50 / p95 s | errors |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.8-27b / original | 42/52 | 100.0% | 0/15 | 11.1% | 86.7% | 7.1% | 50.0% | 1.240 / 1.316 | 0 |
| qwen3-4b / original | 40/52 | 93.3% | 1/15 | 0.0% | 78.8% | 3.6% | 60.0% | 0.209 / 0.253 | 0 |
| qwen3.5-4b / original | 40/52 | 86.7% | 2/15 | 0.0% | 71.1% | 3.6% | 40.0% | 0.287 / 0.329 | 0 |
| LFM2.5-1.2B seccal FT Q8_0 / original | 39/52 | 80.0% | 3/15 | 11.1% | 78.8% | 3.6% | 30.0% | n/a (legacy c=4) | 0 |
| qwen3.5-9b / original | 38/52 | 80.0% | 3/15 | 0.0% | 74.3% | 7.1% | 30.0% | 0.429 / 0.460 | 0 |
| ministral3-3b / original | 37/52 | 86.7% | 2/15 | 44.4% | 83.3% | 21.4% | 40.0% | 0.205 / 0.218 | 0 |
| LFM2.5-1.2B seccal FT Q4_K_M / original | 37/52 | 73.3% | 2/15 | 11.1% | 80.6% | 7.1% | 30.0% | n/a (legacy c=4) | 0 |
| smollm3-3b / original | 35/52 | 40.0% | 9/15 | 11.1% | 62.2% | 0.0% | 20.0% | 0.165 / 0.198 | 0 |
| gemma4-e2b / original | 33/52 | 33.3% | 10/15 | 0.0% | 59.6% | 0.0% | 10.0% | 0.195 / 0.212 | 0 |
| granite4-micro / original | 32/52 | 20.0% | 5/15 | 11.1% | 68.3% | 0.0% | 20.0% | 0.191 / 0.211 | 0 |
| lfm2.5-8b-a1b / original | 28/52 | 20.0% | 8/15 | 0.0% | 59.5% | 3.6% | 10.0% | 0.163 / 0.174 | 0 |
| lfm2.5-1.2b / original | 25/52 | 0.0% | 13/15 | 0.0% | 53.2% | 0.0% | 0.0% | 0.094 / 0.100 | 0 |
| lfm2-2.6b / original | 24/52 | 13.3% | 3/15 | 44.4% | 69.2% | 0.0% | 20.0% | 0.194 / 0.203 | 0 |
| phi4-mini / original | 22/52 | 0.0% | 1/15 | 44.4% | 75.0% | 0.0% | 10.0% | 0.206 / 0.235 | 0 |
| lfm2.5-2.6b / original | protocol failure | n/a | n/a | n/a | n/a | n/a | n/a | 0.210 / 0.221 | 52 |
| qwen3.8-27b / policy | 44/52 | 93.3% | 0/15 | 22.2% | 87.5% | 0.0% | 60.0% | 1.228 / 1.325 | 0 |
| ministral3-3b / policy | 42/52 | 100.0% | 0/15 | 0.0% | 79.4% | 3.6% | 60.0% | 0.208 / 0.220 | 0 |
| qwen3.5-9b / policy | 41/52 | 86.7% | 2/15 | 0.0% | 77.8% | 0.0% | 40.0% | 0.424 / 0.456 | 0 |
| gpt-oss-safeguard-20b (reasoning) / policy | 41/52 | 73.3% | 3/15 | 22.2% | 73.7% | 0.0% | 40.0% | 0.899 / 2.656 | 0 |
| qwen3-4b / policy | 40/52 | 66.7% | 0/15 | 22.2% | 82.4% | 0.0% | 40.0% | 0.225 / 0.243 | 0 |
| qwen3.5-4b / policy | 38/52 | 73.3% | 4/15 | 0.0% | 69.2% | 3.6% | 30.0% | 0.286 / 0.303 | 0 |
| gemma4-e2b / policy | 35/52 | 46.7% | 6/15 | 0.0% | 65.1% | 0.0% | 20.0% | 0.193 / 0.218 | 0 |
| smollm3-3b / policy | 34/52 | 46.7% | 7/15 | 0.0% | 64.3% | 3.6% | 20.0% | 0.175 / 0.192 | 0 |
| phi4-mini / policy | 30/52 | 26.7% | 1/15 | 33.3% | 76.7% | 0.0% | 20.0% | 0.216 / 0.233 | 0 |
| granite4-micro / policy | 28/52 | 0.0% | 3/15 | 0.0% | 70.0% | 0.0% | 0.0% | 0.197 / 0.215 | 0 |
| lfm2-2.6b / policy | 25/52 | 13.3% | 3/15 | 44.4% | 70.4% | 0.0% | 20.0% | 0.234 / 0.271 | 0 |
| lfm2.5-8b-a1b / policy | 15/52 | 0.0% | 1/15 | 55.6% | 66.7% | 0.0% | 10.0% | 0.190 / 0.221 | 0 |
| lfm2.5-1.2b / policy | 14/52 | 6.7% | 1/15 | 66.7% | 70.0% | 3.6% | 10.0% | 0.113 / 0.130 | 0 |

## Downloads and runtime evidence

Artifact sizes are decimal GB. RSS is sampled process resident memory, not total unified-memory use; do not interpret it as the full Metal allocation or use it alone to certify a fit.

| initial model | GGUF GB | download | runtime | sampled peak process RSS GB |
|---|---|---|---|---|
| lfm2.5-1.2b | 0.73 | verified locally | measured | 0.98 |
| lfm2-2.6b | 1.56 | verified locally | measured | 1.86 |
| lfm2.5-2.6b | 1.67 | verified locally | protocol adapter required | 1.98 |
| qwen3-4b | 2.50 | verified locally | measured | 3.67 |
| qwen3.5-4b | 2.74 | verified locally | measured | 5.36 |
| qwen3.5-9b | 5.68 | verified locally | measured | 8.97 |
| ministral3-3b | 2.15 | verified locally | measured | 2.99 |
| gemma4-e2b | 3.11 | verified locally | measured | 3.55 |

Per-run reports contain uncertainty intervals, tool slices and individual errors. Full per-row predictions, model revisions, artifact hashes, prompt/dataset hashes and server commands are in `eval/out/` (gitignored).
