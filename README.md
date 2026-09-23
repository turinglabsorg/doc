# doc

Scott's sidekick: small, fast, typed judgments from [TypeSafe's Jev](https://docs.typesafe.ai)
wired into Claude Code, where ordinary code needs a bit of common sense.

| Part | Hook / command | What it does |
|---|---|---|
| `publish_guard` | PreToolUse (Bash) | Before `gh`/`grog` publishes a comment: exact rules in code (local paths, attribution lines), Jev for local-only state, effort estimates, process narration, billing. Deny with reasons, or ask when borderline. |
| `reply_check` | Stop | Blocks a final reply that gives an effort or time estimate, once; the second stop always passes. |
| `skill_router` | UserPromptSubmit | Ranks every skill against the turn, re-checks the top three, adds one `<skill_relevance>` line the agent may ignore. |
| `doc "<task>"` | CLI | Mechanical, low-risk work the router is confident about goes to `oclaude`; everything else to `claude`. `--dry-run`, `-p`. |

The TypeSafe key lives in hush as `TYPESAFE_API_KEY`; `bin/doc-hook` injects it with
`hush run --redact`. Without hush or python3 a hook checks nothing and exits 0.
Every Jev call (tokens, latency) and every decision (`publish_guard: deny`,
`reply_check: passed`, `skill_router: suggested:devo`, `route: oclaude`) is logged —
never the text that was judged — to `~/.cache/doc/usage.jsonl`.

## Install

Register the hooks in `~/.claude/settings.json`:

```json
"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/doc/bin/doc-hook publish_guard", "timeout": 20}]}],
"Stop": [{"hooks": [{"type": "command", "command": "~/doc/bin/doc-hook reply_check", "timeout": 20}]}],
"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "~/doc/bin/doc-hook skill_router", "timeout": 20}]}]
```

and link the CLI: `ln -s ~/doc/bin/doc /usr/local/bin/doc`.

## Tests

```bash
PYTHONPATH=. python3 -m unittest tests.test_offline
hush run --name TYPESAFE_API_KEY --env TYPESAFE_API_KEY --redact -- env PYTHONPATH=. python3 -m unittest tests.test_live
```

## Limits

Jev reads literally, doesn't count or compare dates, and content written to steer
it can move an answer (see its jaggedness page). So these hooks only add checks:
none of them allows anything a rule forbids. `publish_guard` sees the command text,
so a comment posted by a script it can't read is not checked.
