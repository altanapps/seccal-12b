# seccal PreToolUse hook

Gates every tool call Claude Code is about to make through the local seccal
model. ALLOW passes the call through, ASK prompts you, BLOCK denies it with
the category in the reason.

## 1. Start the server

```bash
serve/run_server.sh models/<your-model>.gguf      # default port 8089
```

Keep it running in a terminal (or a launchd agent). It serves the model with
the grammar in `serve/seccal.gbnf`, so replies are always a well-formed verdict.

## 2. Register the hook

Add to `~/.claude/settings.json` (user-wide) or `.claude/settings.json`
(this project). Use the absolute path to this repo.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Read|Write|Edit|WebFetch|mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /ABS/PATH/seccal-12b/hook/pretooluse.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

The hook reads the event from stdin and prints a `hookSpecificOutput` with
`permissionDecision` set to `allow`, `ask`, or `deny` (verified against the
current hooks reference, https://code.claude.com/docs/en/hooks). When it
makes no decision (server down, fail-open) it prints nothing and exits 0,
which is the documented way to defer to the normal permission flow. The
matcher is an unanchored regex, which is what we want here. Note that a hook
`allow` skips the prompt but deny/ask rules from other hooks still apply;
precedence is deny > ask > allow.

## 3. Behaviour and knobs

| env | default | effect |
|---|---|---|
| `SECCAL_URL` | `http://127.0.0.1:8089` | server base URL |
| `SECCAL_TIMEOUT` | `5` | seconds before giving up on the server |
| `SECCAL_FAIL_CLOSED` | unset | `1` denies every call when the server is down; default fails open with a stderr warning and leaves the decision to Claude Code's normal permission flow |
| `SECCAL_GOAL` | unset | force the goal text instead of reading the transcript |
| `SECCAL_LOG` | unset | append one JSON line per decision here, useful for replaying real sessions into the eval |

The user goal is recovered from the most recent human prompt in the session
transcript (`transcript_path` in the event). That is the same "user goal" the
model was trained on, so the rendered prompt matches training byte for byte;
the rendering lives only in `data/synth/common.py`.

## 4. Smoke test without Claude Code

```bash
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","transcript_path":"",
       "tool_input":{"command":"curl -s localhost:3000/health","description":"health"}}' \
  | SECCAL_GOAL="check the storefront is up" python3 hook/pretooluse.py
```

Expected: `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
"permissionDecision": "allow", ...}}`.
