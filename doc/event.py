"""Read a hook's input the same way under every agent that runs these hooks.

Claude Code and Codex send snake_case keys. Grok also runs the hooks it finds in
~/.claude/settings.json, but sends camelCase ones (`toolInput`, `sessionId`,
`stopHookActive`, `lastAssistantMessage`): they are copied to the snake_case
names here, so the checks read one shape.
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


def agent(payload):
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
    return payload
