# Model selection and evaluation plan — 24 October 2026

Use this 48 GB Apple M5 Pro to compare small deployment models against a few larger local quality references before spending time on post-training. The initial eight-checkpoint download is complete: 20.14 GB. Seven checkpoints support the current direct verdict protocol; one needs an adapter. The approved working-time selection is six additional checkpoints, 39.75 GB, with the 35B checkpoint deferred to a separate run. All inference stays local. Subsequent Ministral-3-3B QLoRA training completed locally at a maximum sampled 5.34 GB, under the 24 GB working cap; see the [training report](ministral_finetune.md). The original selection recommendations below are retained for context.

## Approved next phase (35B deferred while the user works)

1. Use the initial validation comparison (original and full-policy prompts as distinct tracks) to establish the small-model reference. Keep **Ministral-3-3B and Qwen3-4B** as provisional SFT candidates. Investigate the LFM2.5-2.6B native reasoning/template mismatch separately; exclude its failed direct protocol run from model-quality ranking.
2. Expand to four small independent comparisons: **LFM2.5-8B-A1B, SmolLM3-3B, Phi-4-mini and Granite 4.0 Micro**. Add three local quality references: **Qwen3.8-27B, Qwen3.6-35B-A3B and gpt-oss-safeguard-20B**. The approved working-time subset excludes the 35B model: six GGUF checkpoints, 39.75 GB. The remaining 22.13 GB 35B checkpoint is deferred. First smoke-test each architecture; run sequentially. Safeguard needs its own policy/reasoning adapter and budget, and must not be mixed silently with direct no-thinking runs. The 35B reference is explicitly excluded from this run. Keep the 24 GB cap throughout this phase; any later change of that cap belongs to a separately authorized run.
3. Select **two small models for LoRA/QLoRA SFT**: the best safety/latency tradeoff and one independent-family challenger. Preserve Qwen3-4B as a controlled candidate because its CUDA training preset already exists. Keep the existing fine-tuned LFM Q4 as a reference. Port one supported small-model recipe to MLX if local training is desired; otherwise prepare the existing Colab/CUDA path. No claim that the current CUDA script runs on macOS.
4. Add an independently reviewed, scenario-separated evaluation set before claiming deployment safety: target at least **300 new held-out calls**, including **100 BLOCK** and **80 ASK**, with MCP calls, goal flips, written-but-not-executed code, argument injection/forged approval, obfuscation, and destructive-plan inspection versus execution. Freeze it before comparing post-trained models. Never let paired variants cross splits. Use registry/static checks for package identity rather than expecting memorized typosquat detection.
5. Compare the selected SFT models with the best unmodified checkpoint, quantize finalists at Q4 and Q8, then run the existing frozen test set once after choices are fixed. Consider preference optimization only if reviewed preference pairs expose a residual ASK/BLOCK boundary problem; the present supervised dataset is not a DPO dataset.

Proposed deployment target to agree before selection: **p95 at most 1 second preferred, 2 seconds a fallback**, no malformed/transport errors, and no increase in BLOCK→ALLOW errors to gain ASK recall or accuracy. Report ALLOW precision, false blocks, ASK recall and goal-flip consistency together. These latency values are targets, not guarantees. A larger model may be useful as an offline reviewer or distillation teacher even if it is too slow as an inline hook.

## What has been prepared

- A 54-checkpoint catalog with publisher links, memory-fit and training-feasibility classifications, public GGUF sizes, pinned revisions and SHA-256 hashes where available.
- Eight initial GGUF downloads: original LFM2.5-1.2B, LFM2-2.6B, LFM2.5-2.6B, Qwen3-4B-Instruct-2507, Qwen3.5-4B, Qwen3.5-9B, Ministral-3-3B-Instruct and Gemma-4-E2B-IT.
- A resumable verified downloader and sequential local server/evaluation runner, plus failure-aware metrics, uncertainty intervals, prompt/model/dataset provenance, and a combined validation comparison.
- A process lock prevents simultaneous sweep invocations, even on different ports. Each server must exit before the next loads. A 24 GB default model/runtime estimate cap leaves roughly half the RAM for normal work. Downloads stream to disk without loading model weights.
- A distinct full-policy zero-shot prompt track. The old hook, training renderer, canonical data and existing split assignments remain as they were.
- Live download/runtime evidence and results are in [base_model_comparison.md](base_model_comparison.md). Commands and output definitions are in [eval/README.md](../eval/README.md).

The full-policy pilot favors **Ministral-3-3B** as a small safety reference (15/15 gold BLOCK calls blocked, 42/52 correct, p95 about 0.22 s), but it recognizes 0/9 ASK cases. **Qwen3-4B** returns ALLOW on 0/15 gold BLOCK calls, recognizes 2/9 ASK cases, and has p95 about 0.24 s; five gold BLOCK cases become ASK instead. These are different tradeoffs, not a conclusive winner. Neither result establishes safety with only 15 BLOCK cases. No canonical labels, test rows or hook settings were changed.

## How to read the fit classification

Hardware inspected: Apple M5 Pro, 20 GPU cores, 48 GB unified memory; installed llama.cpp build 11669 (commit 620d2225c), Metal backend; about 1.4 TB disk available at inspection. This is shared CPU/GPU memory, not 48 GB of dedicated VRAM.

Artifact sizes below use decimal GB. Runtime columns are **planning estimates**, generally GGUF bytes plus 1–5 GB for state/cache/runtime, assuming one loaded model, one server slot and 4096-token context, without a vision projector. Keep roughly 8–12 GB of additional memory available for macOS and normal apps. Actual fit depends on the architecture, context, backend and other running processes. The matrix now imposes a conservative **24 GB** estimated runtime ceiling while the user works; raising it for a larger reference is an explicit run configuration. Only one model is loaded at a time.

**Yes** means a plausible memory fit at the listed quantization. It does not certify compatibility with this installed llama.cpp until a smoke test succeeds. **No practical Q4** means it is outside this useful operating envelope; extreme Q2/Q3 quantization, swapping or CPU paging is a separate experiment rather than the proposed deployment. MoE active parameter counts affect compute; the full total model still has to be stored.

For local post-training, **plausible** means small enough to investigate short-context, low-batch QLoRA on MLX, conditional on architecture support and measured activations/optimizer memory. **Borderline** needs tighter settings and a measured pilot. **Remote preferred** is not a proof of impossibility on 48 GB; it avoids promising local training fit from inference size alone. The existing Unsloth script requires CUDA for every preset. Full-weight training is a different, substantially larger memory budget.

“Base-model evaluation” here means the released checkpoint **before seccal training**, usually already instruct-tuned by the publisher. Raw pretraining `-Base` variants are not substituted: with only 399 supervised training rows, the instruct checkpoints are the main starting point.

## Initial download and pilot evaluation

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [LiquidAI/LFM2.5-1.2B-Instruct](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct) | 1.170 | 0.73 / Q4_K_M | 1.7–4.7 | Yes | Plausible; new MLX recipe |
| [LiquidAI/LFM2-2.6B](https://huggingface.co/LiquidAI/LFM2-2.6B) | 2.569 | 1.56 / Q4_K_M | 2.6–5.6 | Yes | Plausible; new MLX recipe |
| [LiquidAI/LFM2.5-2.6B](https://huggingface.co/LiquidAI/LFM2.5-2.6B) | 2.697 | 1.67 / Q4_K_M | 2.7–5.7 | Yes | Plausible; new MLX recipe |
| [Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) | 4.022 | 2.50 / Q4_K_M | 3.5–6.5 | Yes | Plausible; new MLX recipe |
| [Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | 4.660 | 2.74 / Q4_K_M | 3.7–6.7 | Yes | Plausible; new MLX recipe |
| [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) | 9.653 | 5.68 / Q4_K_M | 6.7–9.7 | Yes | Plausible; new MLX recipe |
| [mistralai/Ministral-3-3B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512) | 3.849 | 2.15 / Q4_K_M | 3.1–6.1 | Yes | [Measured MLX QLoRA: 5.34 GB peak](ministral_finetune.md) |
| [google/gemma-4-E2B-it](https://huggingface.co/google/gemma-4-E2B-it) | 5.123 | 3.11 / Q4_K_M | 4.1–7.1 | Yes | Plausible; new MLX recipe |

LFM2.5-2.6B fits and loads on Metal, but its publisher template unconditionally opens a thinking span. On this installed llama.cpp the grammar-constrained verdict appears in `reasoning_content` with empty final `content`, despite `--reasoning off`. A zero thinking budget conflicts with the grammar. The 52 direct-protocol errors are retained for diagnosis; this is an integration blocker, not a score of the model's classification ability. The other seven initial checkpoints work with the direct protocol.

## Other small deployment candidates

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | 0.873 | 0.53 / Q4_K_M | 1.5–5.5 | Yes | Plausible; new MLX recipe |
| [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | 2.274 | 1.28 / Q4_K_M | 2.3–6.3 | Yes | Plausible; new MLX recipe |
| [LiquidAI/LFM2.5-8B-A1B](https://huggingface.co/LiquidAI/LFM2.5-8B-A1B) | 8.468 | 5.16 / Q4_K_M | 6.2–10.2 | Yes | Plausible; new MLX recipe |
| [HuggingFaceTB/SmolLM3-3B](https://huggingface.co/HuggingFaceTB/SmolLM3-3B) | 3.075 | 1.92 / Q4_K_M | 2.9–6.9 | Yes | Plausible; new MLX recipe |
| [microsoft/Phi-4-mini-instruct](https://huggingface.co/microsoft/Phi-4-mini-instruct) | 3.836 | 2.49 / Q4_K_M | 3.5–7.5 | Yes | Plausible; new MLX recipe |
| [ibm-granite/granite-4.0-micro](https://huggingface.co/ibm-granite/granite-4.0-micro) | 3.403 | 2.10 / Q4_K_M | 3.1–7.1 | Yes | Plausible; new MLX recipe |
| [meta-llama/Llama-3.2-3B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct) | 3.213 | 2.02 / Q4_K_M | 3.0–7.0 | Yes | Plausible; new MLX recipe |
| [google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it) | 7.996 | 4.98 / Q4_K_M | 6.0–10.0 | Yes | Plausible; new MLX recipe |
| [mistralai/Ministral-3-8B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512) | 8.918 | 5.20 / Q4_K_M | 6.2–10.2 | Yes | Plausible; new MLX recipe |
| [nvidia/NVIDIA-Nemotron-Nano-9B-v2](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2) | 8.888 | 6.53 / Q4_K_M | 7.5–11.5 | Yes | Plausible; new MLX recipe |

## Larger local quality references

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | 27.781 | 16.46 / UD-Q4_K_M | 17.5–21.5 | Yes | Remote preferred |
| [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | 35.952 | 22.13 / Q4_K_M | 23.1–27.1 | Yes | Remote preferred |
| [openai/gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | 20.915 | 12.11 / MXFP4 | 13.1–17.1 | Yes | Remote preferred |
| [google/gemma-4-12B-it](https://huggingface.co/google/gemma-4-12B-it) | 11.960 | 7.12 / Q4_K_M | 8.1–12.1 | Yes | Borderline; measured QLoRA pilot |
| [google/gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it) | 25.806 | 16.95 / Q4_K_M | 17.9–21.9 | Yes | Remote preferred |
| [google/gemma-4-31B-it](https://huggingface.co/google/gemma-4-31B-it) | 31.273 | 18.32 / Q4_K_M | 19.3–23.3 | Yes | Remote preferred |
| [mistralai/Ministral-3-14B-Instruct-2512](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512) | 13.945 | 8.24 / Q4_K_M | 9.2–13.2 | Yes | Borderline; measured QLoRA pilot |
| [LiquidAI/LFM2-24B-A2B](https://huggingface.co/LiquidAI/LFM2-24B-A2B) | 23.844 | 14.42 / Q4_K_M | 15.4–19.4 | Yes | Remote preferred |
| [ibm-granite/granite-4.0-h-small](https://huggingface.co/ibm-granite/granite-4.0-h-small) | 32.207 | 19.48 / Q4_K_M | 20.5–24.5 | Yes | Remote preferred |
| [nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) | 31.578 | 24.57 / Q4_K_M | 25.6–29.6 | Yes | Remote preferred |

## Optional comparisons and older controls

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [Qwen/Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B) | 27.781 | 16.74 / Q4_K_M | 17.7–21.7 | Yes | Remote preferred |
| [Qwen/Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B) | 35.952 | 22.02 / Q4_K_M | 23.0–27.0 | Yes | Remote preferred |
| [Qwen/Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B) | 27.781 | 16.82 / Q4_K_M | 17.8–21.8 | Yes | Remote preferred |
| [Qwen/Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B) | 8.191 | 5.03 / Q4_K_M | 6.0–10.0 | Yes | Plausible; new MLX recipe |
| [Qwen/Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B) | 14.768 | 9.00 / Q4_K_M | 10.0–14.0 | Yes | Borderline; measured QLoRA pilot |
| [Qwen/Qwen3-32B](https://huggingface.co/Qwen/Qwen3-32B) | 32.762 | 19.76 / Q4_K_M | 20.8–24.8 | Yes | Remote preferred |
| [Qwen/Qwen3-30B-A3B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507) | 30.532 | 18.56 / Q4_K_M | 19.6–23.6 | Yes | Remote preferred |
| [meta-llama/Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct) | 8.030 | 4.92 / Q4_K_M | 5.9–9.9 | Yes | Plausible; new MLX recipe |
| [google/gemma-3-12b-it](https://huggingface.co/google/gemma-3-12b-it) | 12.187 | 7.30 / Q4_K_M | 8.3–12.3 | Yes | Borderline; measured QLoRA pilot |
| [microsoft/phi-4](https://huggingface.co/microsoft/phi-4) | 14.660 | 8.89 / Q4_K_M | 9.9–13.9 | Yes | Borderline; measured QLoRA pilot |
| [deepseek-ai/DeepSeek-R1-Distill-Qwen-14B](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Qwen-14B) | 14.770 | 8.99 / Q4_K_M | 10.0–14.0 | Yes | Borderline; measured QLoRA pilot |

## Specialized judges and discriminative alternatives

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [openai/gpt-oss-safeguard-20b](https://huggingface.co/openai/gpt-oss-safeguard-20b) | 21.512 | 11.62 / Q4_K_M | 12.6–16.6 | Yes | Remote preferred |
| [meta-llama/Llama-Prompt-Guard-2-86M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M) | 0.279 | not pinned / separate backend | 1.2–2.5 | Yes | Small; different classifier objective |
| [meta-llama/Llama-Prompt-Guard-2-22M](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M) | 0.071 | not pinned / separate backend | 0.4–1.5 | Yes | Small; different classifier objective |
| [ibm-granite/granite-guardian-4.1-8b](https://huggingface.co/ibm-granite/granite-guardian-4.1-8b) | 8.381 | not pinned / separate backend | 6.0–10.0 | Yes | New architecture/schema workflow |
| [Qwen/Qwen3Guard-Gen-4B](https://huggingface.co/Qwen/Qwen3Guard-Gen-4B) | 4.411 | 2.72 / Q4_K_M | 3.7–7.7 | Yes | New architecture/schema workflow |
| [meta-llama/Llama-Guard-3-8B](https://huggingface.co/meta-llama/Llama-Guard-3-8B) | 8.030 | 4.92 / Q4_K_M | 5.9–9.9 | Yes | New architecture/schema workflow |
| [answerdotai/ModernBERT-base](https://huggingface.co/answerdotai/ModernBERT-base) | 0.150 | not pinned / separate backend | 0.5–2.0 | Yes | Small; new MPS classifier recipe |
| [answerdotai/ModernBERT-large](https://huggingface.co/answerdotai/ModernBERT-large) | 0.396 | not pinned / separate backend | 1.0–3.0 | Yes | Small; new MPS classifier recipe |

gpt-oss-safeguard is designed for written-policy safety classification and merits a dedicated policy track. Granite Guardian has bring-your-own-criteria capabilities. Qwen3Guard, Llama Guard and Prompt Guard use different native objectives; a content-safety or injection label is not equivalent to authorization for a specific user goal. ModernBERT requires a trained three-class head, has no useful zero-shot chat baseline, and offers a smaller discriminative experiment. Prompt Guard names and stored parameter counts differ because the publisher size name does not count all embedding parameters.

## Outside the practical 48 GB Q4 envelope

| checkpoint | total B (approx.) | GGUF GB / quant | runtime GB (estimate) | inference memory fit | local post-training |
|---|---:|---|---|---|---|
| [meta-llama/Llama-3.3-70B-Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | 70.554 | 42.52 / Q4_K_M | 43.5–47.5 | No practical Q4 | Remote only for this plan |
| [Qwen/Qwen3-Next-80B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct) | 81.325 | 48.51 / Q4_K_M | 49.5–53.5 | No practical Q4 | Remote only for this plan |
| [Qwen/Qwen3-Coder-Next](https://huggingface.co/Qwen/Qwen3-Coder-Next) | 79.674 | 48.53 / Q4_K_M | 49.5–53.5 | No practical Q4 | Remote only for this plan |
| [openai/gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) | 116.829 | 63.39 / MXFP4 | 64.4–68.4 | No practical Q4 | Remote only for this plan |
| [Qwen/Qwen3.5-122B-A10B](https://huggingface.co/Qwen/Qwen3.5-122B-A10B) | 125.086 | 76.54 / Q4_K_M | 77.5–81.5 | No practical Q4 | Remote only for this plan |
| [deepseek-ai/DeepSeek-V3.2](https://huggingface.co/deepseek-ai/DeepSeek-V3.2) | 685.355 | not pinned / separate backend | 425.9–429.9 | No practical Q4 | Remote only for this plan |
| [Qwen/Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) | 180.000 | not pinned / separate backend | 112.6–116.6 | No practical Q4 | Remote only for this plan |

The 70B checkpoint has a roughly 42.5 GB Q4 file before runtime and the OS. It may be possible to force a lower-precision or paged run, but it is not the comfortable resident local gate proposed here. Models in the 80B–685B total-weight class do not become suitable merely because their active expert count is small.

## Evaluation protocol

Run unchanged canonical validation rows first. For each direct instruct model use the same message text, its own native chat template, the same constrained output grammar, temperature 0, thinking off, 4096-token context, 96 output tokens, two unscored warmups, request concurrency 1, and one model loaded at a time. Keep original and full-policy prompts separate. Larger reasoning models get an explicitly separate token/latency budget and native Harmony/reasoning parsing; do not penalize them with a 48-token budget and call that a model-quality result.

Rank on safety errors and user friction jointly: BLOCK recall, BLOCK→ALLOW, ALLOW precision, ASK recall, false blocks, balanced accuracy/macro F1, goal-flip and twin consistency, errors, tool/category/modifier slices and warmed p50/p95 latency. Record model and quantizer source/revision, SHA-256, server version and command, prompt and dataset hashes, context and thinking settings, completion reason and sampled process RSS. Compare cold loading separately from warm per-call latency; the current automated runner records warm latency, not a calibrated cold-start benchmark. Sampled RSS is not total unified-memory consumption.

The validation set contains only 15 BLOCK and nine ASK examples. Wilson intervals and exact error counts must accompany claims; 0/15 misses still gives an upper 95% Wilson bound of about 20%. Multiple comparisons on the same 52 rows make selection optimistic. The 49-row historical test is already public in the repository, so a new independent holdout is essential for a stronger claim. Do not call a failure-heavy model safe because requests that failed did not return ALLOW.

## Training and deployment choices after approval

Use a short, fixed pilot (same training rows, seed, adapter rank and held-out policy) to compare two small models before extending training. Verify assistant-only loss masks against each native template; ChatML markers and LFM module names cannot be copied into Gemma, Phi, Mistral or MoE recipes. Keep quantization comparisons within one trained checkpoint. Measure local memory during a short QLoRA pilot rather than extrapolating from a GGUF file. Prefer supervised training and targeted data first; defer DPO/RL until there is a supported reward/preference dataset and a demonstrated need.

Use a larger reference model to suggest labels or distillation targets only on training material; retain blind human/independent adjudication. Never train on held-out decisions or on the larger model’s unreviewed answer just because it is larger. Existing hook hardening is a separate prerequisite to using any verdict as an enforceable permission gate.

## Sources and reproducibility

Every model row links its publisher checkpoint; [model_catalog.json](../eval/model_catalog.json) records exact retrieved revisions and GGUF artifact hashes. Public metadata was inspected on 24 October 2026. Most GGUF artifacts are community conversions (Unsloth/Bartowski/etc.), rather than publisher-supplied weights; the catalog explicitly records both sources. Metadata pinning gives reproducibility, not a claim that a third-party quantizer is the publisher.

- [MLX-LM LoRA/QLoRA documentation](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md) describes an Apple Silicon fine-tuning route; support and memory still need a per-architecture pilot.
- [Qwen3.5-4B publisher card](https://huggingface.co/Qwen/Qwen3.5-4B), [Qwen3.6-35B-A3B card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B), and [Qwen3.8-27B card](https://huggingface.co/Qwen/Qwen3.8-27B) identify the current family checkpoints considered alongside the repository’s Qwen3 preset.
- [Gemma 4 publisher family page](https://deepmind.google/models/gemma/gemma-4/) and [Liquid model library](https://docs.liquid.ai/lfm/models/complete-library) explain efficient and MoE variants. Effective/active names are not stored-weight footprints.
- [OpenAI gpt-oss-20b documentation](https://developers.openai.com/api/docs/models/gpt-oss-20b) and [gpt-oss-safeguard guide](https://developers.openai.com/cookbook/articles/gpt-oss-safeguard-guide) cover local open weights and custom-policy classification. These are local downloads, not hosted API calls.
- [IBM Guardian documentation](https://www.ibm.com/granite/docs/models/guardian) and [ModernBERT publisher card](https://huggingface.co/answerdotai/ModernBERT-base) motivate the separate specialist and encoder tracks.

Licenses differ. The catalog preserves each publisher’s license identifier; Liquid’s custom license, Llama terms and older Gemma terms should not be inferred from an Apache-licensed alternative. Weight downloads do not change the project’s licensing.
