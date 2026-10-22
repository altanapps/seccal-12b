# seccal-12b

On-device tool-call risk scorer: a fine-tuned `LiquidAI/LFM2.5-1.2B-Instruct` that judges a coding agent's pending tool call (given the user's goal) and returns an ALLOW / ASK / BLOCK verdict, served locally via llama.cpp from a Claude Code `PreToolUse` hook.
