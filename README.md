# seccal-12b

On-device tool-call risk scorer: a fine-tuned `LiquidAI/LFM2.5-1.2B-Instruct` that judges a coding agent's pending tool call (given the user's goal) and returns an ALLOW / ASK / BLOCK verdict, served locally via llama.cpp from a Claude Code `PreToolUse` hook.

## Dataset summary

**500 reviewed training rows** across four batches (pilot 101, batch B 99, batch D 150, batch E 150), each a pending tool call judged against the user's goal. Canonical files: `data/synth/out/accepted.jsonl` (398 rows where the generator and an independent blind judge agreed) and `data/synth/out/adjudicated.jsonl` (102 disagreements resolved by blind-first adjudication). Label policy: `data/LABELING.md`.

### Distribution

- **Verdicts**: ALLOW 277 (55.4%) / ASK 74 (14.8%) / BLOCK 149 (29.8%) — on target (55/15/30)
- **Scenario kinds**: benign 172, injected (prompt-injection attacks) 140, benign_hard (scary-looking but intended) 107, reckless (no attacker, risky mistakes) 81
- **Harm categories** (non-benign): destructive 57, reckless 38, injected_action 36, exfiltration 22, remote_code_exec 22, credential_access 19, supply_chain 12, privilege_escalation 9, persistence 8
- **Tools**: Bash 61%, then Read 9%, Edit 9%, MCP 9%, WebFetch 6%, Write 6%
- **Coverage**: all 20 simulated project environments (17–37 rows each)

### Robustness features

- **96 contrast pairs**: 48 goal-flip pairs (identical command, different goal, different verdict — forces the model to read the goal) and 48 twin pairs (same goal, different command, different verdict)
- **Shortcut-checked**: no single surface feature (URLs/IPs, command length, tool name, goal phrasing, project) predicts the label at >80% on its own; the pilot's URL⇒BLOCK shortcut (81%) was broken in later batches (now ~60%)
- **Adversarial modifiers**: obfuscated attacks (base64, `$IFS`, hex) and judge-injection rows (embedded "security-reviewed/approved" text that must carry zero weight). These currently run below target (obfuscated 3.6% vs ~10%, judge-injection 2.2% vs ~5%) and are the main thing to raise in the next batch.

### Quality process

Every row passed a three-stage gate: schema/consistency validation (`validate.py`), independent blind re-judging (one fresh judge per chunk), and an adversarial reviewer audit. Blind action agreement by batch: pilot 79%, B 98%, D 84.7%, E 90.7% (the D dip is concentrated on the reckless-vs-destructive ASK/BLOCK boundary, resolved in adjudication). Reviewer audits scored 100% label correctness on the 40-row samples for batches D and E (reports in `reports/`). All generator/judge disagreements were resolved by blind-first adjudication; the single escalation (rkD16, `sudo rm -rf` of a whole checkout) was resolved to BLOCK. The full process is documented in `data/synth/PIPELINE.md`.

## Model: first fine-tune

### Recipe

- **Base**: `LiquidAI/LFM2.5-1.2B-Instruct` (1.2 B parameters, hybrid conv + grouped-query attention).
- **Method**: LoRA supervised fine-tuning with Unsloth on a free Colab T4 (`train/sft_unsloth.py`, one-file notebook `train/seccal_colab.ipynb`). Rank 16, alpha 16, dropout 0, on the LFM2.5-specific modules `q_proj, k_proj, v_proj, out_proj, in_proj, w1, w2, w3`.
- **Objective**: loss on the assistant's verdict tokens only (completion-only). 3 epochs, lr 2e-4 cosine, effective batch 8, fp16 on T4, seed 3407. Final train loss 0.085.
- **Data**: 399 train / 52 val / 49 test rows (`data/synth/split.py`: stratified by verdict × kind, contrast pairs never straddle splits, test set frozen), rendered by `common.to_chat` so training, eval, and the hook share one prompt byte for byte.
- **Export and serving**: adapter merged into the base, exported to GGUF `Q4_K_M` (731 MB) and `Q8_0` (1.25 GB), served by `llama-server` with the grammar in `serve/seccal.gbnf` at temperature 0, so every reply is a well-formed verdict and ALLOW can only pair with `benign`.

### Results (frozen test split, 49 rows)

| metric | base model | fine-tuned Q4_K_M | fine-tuned Q8_0 |
|---|---|---|---|
| BLOCK recall | 0.000 | **0.875** | **0.875** |
| attack-miss rate (gold BLOCK → ALLOW) | 0.875 | **0.125** | **0.125** |
| ALLOW precision | 0.556 | **0.889** | 0.833 |
| pair consistency | 0.000 | **0.800** | 0.700 |
| ASK recall | 0.000 | **0.667** | 0.000 |
| action accuracy | 0.510 | **0.857** | 0.796 |

The untrained base model allowed 45 of 49 calls and blocked nothing. Over test + val (101 rows) Q8_0 showed no edge on the safety metrics (attack-miss 0.161 vs 0.129, ASK recall 0.067 vs 0.333) at 1.7× the size, so **Q4_K_M ships**. Full numbers and per-run reports: `reports/eval_summary.md`, `reports/eval_*.md`.

### Known weaknesses (next data batch should target these)

- **ASK is the weak class**: the model polarizes to ALLOW/BLOCK; ASK is only 15% of training rows.
- **Goal-reading is incomplete**: pair consistency is 0.80 on test but 0.30 on val, so it still leans on the command's surface. Expect real-world behaviour closer to val.
- **Two shared attack misses**: a "check whether" goal paired with a command that *applies* a destroy plan, and a one-character typosquat (a 1.2 B model cannot know real package names; supply-chain belongs in a registry check outside the model).
- **Two shared false blocks**: `Write` calls whose file *content* contains `rm -rf`; the model treats scary strings inside written content as if executed.
- At ~13% attack-miss this first model is an advisory/ASK layer, not yet a hard gate. The hook defaults to fail-open; `SECCAL_FAIL_CLOSED=1` inverts it.

### Status and next steps

Dataset (500 rows), first fine-tune, eval, serving, and the `PreToolUse` hook are done. **Iteration 2 is staged**: the training script now takes `--model` presets and `train/seccal_colab_qwen3-4b.ipynb` retrains on `Qwen3-4B-Instruct-2507` (Apache-2.0, same prompt format) for comparison against the iteration-1 numbers above; see `train/README.md`. Remaining: run that retrain and eval, install the hook in real sessions with `SECCAL_LOG` on to collect live decisions, and generate the next batch targeting ASK / goal-flip pairs / obfuscation and judge-injection (both under target).

A source-only security audit (Cloudflare security-audit skill, quick profile) was run on this repository; its artifacts live outside the repo. Before registering the hook in real sessions, apply its recommendations: ask/deny-only mode, isolate the hook's code from the working tree, authenticate the local verdict server, cap `tool_input` size, anchor and widen the matcher, and fix the fail-closed exception gap. The notebook bundle integrity check it recommended is implemented (`make_colab_notebook.py --check`).
