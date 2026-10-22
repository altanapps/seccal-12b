# seccal-12b

On-device tool-call risk scorer: a fine-tuned `LiquidAI/LFM2.5-1.2B-Instruct` that judges a coding agent's pending tool call (given the user's goal) and returns an ALLOW / ASK / BLOCK verdict, served locally via llama.cpp from a Claude Code `PreToolUse` hook.

## Dataset summary

**200 reviewed training rows** across two batches (pilot 101, batch B 99), each a pending tool call judged against the user's goal. Canonical files: `data/synth/out/accepted.jsonl` (162 rows where the generator and an independent blind judge agreed) and `data/synth/out/adjudicated.jsonl` (38 disagreements resolved by blind-first adjudication). Label policy: `data/LABELING.md`.

### Distribution

- **Verdicts**: ALLOW 110 (55.0%) / ASK 30 (15.0%) / BLOCK 60 (30.0%) — exactly on target
- **Scenario kinds**: benign 67, injected (prompt-injection attacks) 59, benign_hard (scary-looking but intended) 45, reckless (no attacker, risky mistakes) 29
- **Harm categories** (non-benign): destructive 21, injected_action 15, exfiltration 14, reckless 12, remote_code_exec 12, credential_access 7, supply_chain 4, persistence 3, privilege_escalation 2
- **Tools**: Bash 62%, Edit/Read/Write/WebFetch/MCP cover the rest
- **Coverage**: all 20 simulated project environments (7–21 rows each)

### Robustness features

- **36 contrast pairs**: 18 goal-flip pairs (identical command, different goal, different verdict — forces the model to read the goal) and 18 twin pairs (same goal, different command, different verdict)
- **Shortcut-checked**: no single surface feature (URLs, command length, tool name, goal phrasing) predicts the label at >80%; the pilot's URL⇒BLOCK shortcut (81%) was deliberately broken in batch B (now 60%)
- **Adversarial modifiers**: obfuscated attacks (base64, `$IFS`, hex) and judge-injection rows (embedded "security-reviewed/approved" text that must carry zero weight)

### Quality process

Every row passed a three-stage gate: schema/consistency validation (`validate.py`), independent blind re-judging (98% action agreement on batch B), and an adversarial reviewer audit (100% label correctness on the latest 40-row sample; reports in `reports/`). All generator/judge disagreements were resolved by blind-first adjudication; all escalations were human-resolved. The full process is documented in `data/synth/PIPELINE.md`.

### Status and next steps

Data generation and review are complete for this phase. Remaining: train/val/test split assignment (contrast pairs kept within a split), SFT rendering, fine-tuning, evaluation (BLOCK recall on attacks, ALLOW precision, pair consistency), GGUF export, and the `PreToolUse` hook integration.
