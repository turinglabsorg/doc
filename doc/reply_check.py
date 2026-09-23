"""Stop: check the agent's final reply against the chat rules before it stops.
Works for Claude Code (reply read from the transcript) and Codex (reply in the
payload as `last_assistant_message`).

The rule: never give effort or time estimates for work. When the last reply
carries one, the stop is blocked once with the reason, so the agent rewrites
it; a second stop in the same chain always passes, so this cannot loop.
"""

import json
import sys

from doc import jev

BLOCK_AT = 0.8

QUESTION = {
    "effort": jev.noul(
        "Does `reply` estimate how much work, time or effort a task will take or took, such "
        "as hours or days of development, how long it will take to build something, or "
        "complexity expressed as time?",
        yes="A work-effort estimate for a person or an agent appears",
        no="No work-effort estimate. How long a running process takes (a build, a download, "
           "a timeout, an uptime) and calendar dates are not effort estimates",
    ),
}


def last_reply(transcript_path):
    text = ""
    try:
        with open(transcript_path, encoding="utf-8") as transcript:
            for line in transcript:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") or {}
                if entry.get("type") != "assistant" or message.get("role") != "assistant":
                    continue
                parts = [block.get("text", "") for block in message.get("content") or []
                         if isinstance(block, dict) and block.get("type") == "text"]
                if any(part.strip() for part in parts):
                    text = "\n".join(parts)
    except OSError:
        return ""
    return text


def judge(reply):
    answers = jev.ask({"reply": reply[:20000]}, QUESTION, purpose="reply_check")
    return answers["effort"]["noul"]


def main():
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        return
    # Codex passes the reply itself; Claude Code only points at its transcript.
    reply = payload.get("last_assistant_message") or last_reply(payload.get("transcript_path") or "")
    if len(reply.strip()) < 40:
        return
    try:
        value = judge(reply)
    except jev.JevError:
        return
    jev.note("reply_check", "blocked" if value >= BLOCK_AT else "passed")
    if value >= BLOCK_AT:
        print(json.dumps({
            "decision": "block",
            "reason": "doc: your last reply gives an effort or time estimate for work (%.2f), "
                      "which the user's rules forbid. Rewrite it without any estimate." % value,
        }))


if __name__ == "__main__":
    main()
