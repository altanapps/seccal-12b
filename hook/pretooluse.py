#!/usr/bin/env python3
"""Claude Code PreToolUse hook backed by a local seccal llama-server.

Reads the PreToolUse event JSON from stdin, recovers the user's current goal
from the session transcript, renders the prompt with data/synth/common.py
(the same bytes used for training and eval), asks the local server for a
verdict, and returns a permission decision:
  ALLOW -> "allow"   ASK -> "ask"   BLOCK -> "deny"

Environment:
  SECCAL_URL           server base URL (default http://127.0.0.1:8089)
  SECCAL_TIMEOUT       seconds to wait for the server (default 5)
  SECCAL_FAIL_CLOSED   "1" to deny when the server is unreachable; default is
                       fail-open: no decision is emitted and Claude Code's
                       normal permission flow applies, with a warning on stderr
  SECCAL_GOAL          overrides the goal recovered from the transcript
  SECCAL_LOG           path to append one JSON line per decision (optional)
Only the standard library is used, so the hook runs under the system python.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synth"))
from common import SYSTEM_PROMPT, render_user_prompt  # noqa: E402

DECISION = {"ALLOW": "allow", "ASK": "ask", "BLOCK": "deny"}


def goal_from_transcript(path: str | None) -> str | None:
    """Most recent human-authored user turn in a Claude Code transcript JSONL."""
    if not path:
        return None
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "user":
            continue
        msg = ev.get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            text = "\n".join(p for p in parts if p)
        else:
            continue
        text = text.strip()
        # Skip tool-result turns and system-injected wrappers; keep real prompts.
        if not text or text.startswith("<") or "tool_result" in str(content)[:200]:
            continue
        return text[:600]
    return None


def ask_server(url: str, goal: str, tool_name: str, tool_input, timeout: float) -> tuple[str, str]:
    row = {"user_goal": goal, "tool_name": tool_name, "tool_input": tool_input}
    body = json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": render_user_prompt(row)},
        ],
        "temperature": 0,
        "max_tokens": 48,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    text = data["choices"][0]["message"]["content"].strip()
    obj = json.loads(text)
    return str(obj["action"]), str(obj["category"])


def emit(decision: str | None, reason: str) -> None:
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if decision:
        out["hookSpecificOutput"]["permissionDecision"] = decision
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(out))


def log(record: dict) -> None:
    p = os.environ.get("SECCAL_LOG")
    if not p:
        return
    try:
        with open(p, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # not a hook event we understand; stay out of the way
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    goal = os.environ.get("SECCAL_GOAL") or goal_from_transcript(event.get("transcript_path")) or "(no user goal available)"

    url = os.environ.get("SECCAL_URL", "http://127.0.0.1:8089")
    timeout = float(os.environ.get("SECCAL_TIMEOUT", "5"))
    fail_closed = os.environ.get("SECCAL_FAIL_CLOSED") == "1"

    try:
        action, category = ask_server(url, goal, tool_name, tool_input, timeout)
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as e:
        log({"tool_name": tool_name, "error": str(e), "fail_closed": fail_closed})
        if fail_closed:
            emit("deny", f"seccal: server unreachable ({e}); SECCAL_FAIL_CLOSED=1")
        else:
            print(f"seccal: server unreachable ({e}); failing open", file=sys.stderr)
            emit(None, "")
        return 0

    decision = DECISION.get(action)
    reason = f"seccal {action} ({category}) for goal: {goal[:120]}"
    log({"tool_name": tool_name, "tool_input": tool_input, "goal": goal, "action": action, "category": category})
    emit(decision, reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
