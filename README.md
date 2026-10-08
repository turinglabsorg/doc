# doc

Scott's sidekick: small, fast, typed judgments from [TypeSafe's Jev](https://docs.typesafe.ai)
wired into Claude Code, Codex, Grok and Hermes, where ordinary code needs a bit of common sense.

| Part | Hook / command | What it does |
|---|---|---|
| `publish_guard` | PreToolUse (Bash) | Before `gh`/`grog` publishes a comment: exact rules in code (local paths, attribution lines), Jev for local-only state, effort estimates, process narration, billing. Deny with reasons, or ask when borderline. |
| `reply_check` | Stop | Blocks a final reply that gives an effort or time estimate, or asks the user to paste a secret into the chat, once; the second stop always passes. Each rule reaches Jev only when its text match fires (a duration, a secret's name), in one request. |
| `skill_router` | UserPromptSubmit | Ranks every skill against the turn; answers at once when the ranking is sure, re-checks the top three only when it is not; adds one `<skill_relevance>` line the agent may ignore, once per skill per session. When the top skill was already suggested it stops after the ranking. Harness texts (stop-hook feedback, compaction summaries) are skipped, and under Grok it never runs. |
| `doc "<task>"` | CLI | Mechanical, low-risk work the router is confident about goes to `oclaude`; everything else to `claude`. `--dry-run`, `-p`. |

The TypeSafe key lives in hush as `TYPESAFE_API_KEY`; `bin/doc-hook` injects it with
`hush run --redact`. Without hush or python3 a hook checks nothing and exits 0.
Every Jev call (tokens, latency) and every decision (`publish_guard: deny`,
`reply_check: passed`, `skill_router: suggested:devo`, `route: oclaude`) is logged to
`~/.cache/doc/usage.jsonl` with the agent that ran it and Jev's scores behind it
(`"scores": {"local_state": 0.98, ...}`), so thresholds can be tuned on real traffic —
never the text that was judged.

Works the same in **Claude Code**, **Codex**, **Grok** and **Hermes**. Codex hands `reply_check` the
reply itself (`last_assistant_message`) and keeps its skills in `~/.codex/skills`;
`skill_router` reads the skills of whichever agent calls it. Grok runs the hooks it
finds in `~/.claude/settings.json` with a camelCase payload (`toolInput`,
`lastAssistantMessage`, `stopHookActive`), which `doc/event.py` reads into the same
shape; it also fires an observe-only Stop at session end, which is skipped, and it
discards what a UserPromptSubmit hook adds, so `skill_router` doesn't run there.
Hermes runs the hooks listed in its own `~/.hermes/config.yaml`, under its event names
(`pre_tool_call`, `pre_llm_call`, `pre_verify`), with the prompt and the reply under
`extra`, and reads back `{"decision": "block"}`, `{"action": "approve"}` and
`{"context": ...}` instead of `hookSpecificOutput`: `doc/event.py` reads and answers in
its shape. Its `pre_verify` fires only on turns that edited files, so there
`reply_check` checks those replies only.

## Install

Register the hooks in `~/.claude/settings.json` and/or `~/.codex/hooks.json`:

```json
"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/doc/bin/doc-hook publish_guard", "timeout": 20}]}],
"Stop": [{"hooks": [{"type": "command", "command": "~/doc/bin/doc-hook reply_check", "timeout": 20}]}],
"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "~/doc/bin/doc-hook skill_router", "timeout": 20}]}]
```

and link the CLI: `ln -s ~/doc/bin/doc /usr/local/bin/doc`.

For Hermes, in `~/.hermes/config.yaml` (its shell tool is `terminal`, and commands run
without a shell):

```yaml
hooks:
  pre_tool_call:
    - {matcher: terminal, command: ~/doc/bin/doc-hook publish_guard, timeout: 20}
  pre_llm_call:
    - {command: ~/doc/bin/doc-hook skill_router, timeout: 20}
  pre_verify:
    - {command: ~/doc/bin/doc-hook reply_check, timeout: 20}
```

Codex runs a hook only once you trust it: on its next start it lists new or
changed hooks for review, or use `/hooks`. Hermes asks once per hook at its first
interactive start (or `hermes --accept-hooks`). Grok needs nothing: it reads the Claude
Code settings unless `[compat.claude] hooks = false` is set in `~/.grok/config.toml`.

`DOC_USAGE_LOG`, `DOC_SKILL_SEEN_DIR` and `DOC_JEV_MODEL` override the defaults;
`bin/doc-hook` and `bin/doc` pass them through `hush run`, whose child otherwise
inherits only the key. The child may run on the host of a container, so these paths
must exist there.

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
