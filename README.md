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

### Status and next steps

Data generation and review are complete for this phase (500 rows). Remaining: train/val/test split assignment (contrast pairs kept within a split), SFT rendering, fine-tuning, evaluation (BLOCK recall on attacks, ALLOW precision, pair consistency), GGUF export, and the `PreToolUse` hook integration.
