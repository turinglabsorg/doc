"""Read a hook's input, and shape its answer, the same way under every agent.

Claude Code and Codex send snake_case keys. Grok also runs the hooks it finds in
~/.claude/settings.json, but sends camelCase ones (`toolInput`, `sessionId`,
`stopHookActive`, `lastAssistantMessage`): they are copied to the snake_case
names here, so the checks read one shape.

Hermes runs the hooks listed in ~/.hermes/config.yaml under its own event names
(`pre_tool_call`, `pre_llm_call`, `pre_verify`) and puts what is not a tool call
under `extra`: the prompt in `extra.user_message`, the reply in
`extra.final_response`, the earlier continuations in `extra.attempt`. It reads
back `{"decision": "block"}`, `{"action": "approve"}` and `{"context": ...}`,
not Claude's `hookSpecificOutput`, so `deny`, `ask` and `context` shape the
answer per agent.
"""

import json
import sys

ALIASES = {
    "tool_input": "toolInput",
    "session_id": "sessionId",
    "transcript_path": "transcriptPath",
    "stop_hook_active": "stopHookActive",
    "last_assistant_message": "lastAssistantMessage",
}
HERMES_EVENTS = {"pre_tool_call", "pre_llm_call", "pre_verify"}


def agent(payload):
    if payload.get("hook_event_name") in HERMES_EVENTS:
        return "hermes"
    # Grok carries the camelCase envelope next to Claude's `hook_event_name`.
    if "hookEventName" in payload or "sessionId" in payload:
        return "grok"
    # Codex hook payloads carry a turn_id, and its transcripts live under ~/.codex.
    if "turn_id" in payload or "/.codex/" in (payload.get("transcript_path") or ""):
        return "codex"
    return "claude"


def read(stream=None):
    payload = json.load(stream or sys.stdin)
    if not isinstance(payload, dict):
        return {"agent": "claude"}
    for snake, camel in ALIASES.items():
        if snake not in payload and camel in payload:
            payload[snake] = payload[camel]
    payload["agent"] = agent(payload)
    if payload["agent"] == "hermes":
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        payload.setdefault("prompt", extra.get("user_message") or "")
        payload.setdefault("last_assistant_message", extra.get("final_response") or "")
        payload.setdefault("stop_hook_active", (extra.get("attempt") or 0) > 0)
    return payload


def permission(payload, decision, reason):
    """The answer that denies (`deny`) or holds for the user (`ask`) a tool call."""
    if payload.get("agent") == "hermes":
        if decision == "deny":
            return {"decision": "block", "reason": reason}
        return {"action": "approve", "message": reason}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}


def context(payload, event_name, text):
    """The answer that adds `text` to what the agent reads next."""
    if payload.get("agent") == "hermes":
        return {"context": text}
    return {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": text}}
