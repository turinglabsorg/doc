"""Stop: check the agent's final reply against the chat rules before it stops.
Works for Claude Code (reply read from the transcript), Codex and Grok (reply in
the payload as `last_assistant_message` / `lastAssistantMessage`).

The rules: never give effort or time estimates for work, and never ask the user
to paste a secret into the chat (secrets travel through hush). When the last
reply breaks one, the stop is blocked once with the reasons, so the agent
rewrites it; a second stop in the same chain always passes, so this cannot loop.

Each rule has a text match that decides first whether Jev is asked at all: most
replies name no duration and no secret. On 1,202 real replies of two weeks
(2026-10-08), 20% named a duration and 14% a secret. Jev then tells an effort
estimate apart from a process time, and a request for a secret value apart from
a mention of a secret's name or of hush.
"""

import json
import re

from doc import event, jev

BLOCK_AT = 0.8

_UNITS = (r"(?:min|minut[io]|minutes?|or[ae]|h|hrs?|hours?|giorn[oi]|gg|days?|settiman[ae]|weeks?|"
          r"mes[ei]|months?)")
DURATION = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:[-–]\s*\d+(?:[.,]\d+)?\s*)?" + _UNITS + r"\b"
    r"|\b(?:un[oa]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|qualche|poch[ie]|alcun[ie]|one|two|"
    r"three|four|five|six|seven|eight|nine|ten|a few|few|several|a couple of|un paio di)\s+" + _UNITS + r"\b"
    r"|mezza giornata|mezz'ora|half an? (?:hour|day)|\bstim[ae]\b|\bstimat[oi]\b|\bestimat\w*|\beffort\b",
    re.IGNORECASE,
)
SECRET = re.compile(
    r"\b(?:api[ _-]?keys?|access[ _-]?keys?|private[ _-]?keys?|tokens?|passwords?|passwd|passphrase|"
    r"secrets?|segret[oi]|credentials?|credenzial[ei]|chiav[ei] (?:api|segret[ae]|di accesso|privat[ae])|"
    r"bearer)\b",
    re.IGNORECASE,
)

RULES = {
    "effort": {
        "match": DURATION,
        "question": jev.noul(
            "Does `reply` estimate how much work, time or effort a task will take or took, such "
            "as hours or days of development, how long it will take to build something, or "
            "complexity expressed as time?",
            yes="A work-effort estimate for a person or an agent appears",
            no="No work-effort estimate. How long a running process takes (a build, a download, "
               "a timeout, an uptime) and calendar dates are not effort estimates",
        ),
        "reason": "gives an effort or time estimate for work",
        "fix": "Rewrite it without any estimate.",
    },
    "secret_request": {
        "match": SECRET,
        "question": jev.noul(
            "Does `reply` ask the user to paste, type or send the value of a secret (an API key, "
            "token, password or credential) directly into this chat?",
            yes="The user is asked to put a secret value into the chat itself",
            no="No secret value is requested in chat. Asking to store or send it through hush or a "
               "Bitwarden Send, or naming a secret without asking for its value, does not count",
        ),
        "reason": "asks the user to paste a secret into the chat",
        "fix": "Ask them to send it through hush instead (a Bitwarden Send), never in chat.",
    },
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


def rules_for(reply):
    """The rules whose text match fires on `reply`: only these reach Jev."""
    return [name for name, rule in RULES.items() if rule["match"].search(reply)]


def judge(reply, rules=None):
    """Jev's score for each of `rules` (all of them when None), in one request."""
    rules = rules or list(RULES)
    answers = jev.ask({"reply": reply[:20000]}, {name: RULES[name]["question"] for name in rules},
                      purpose="reply_check")
    return {name: answers[name]["noul"] for name in rules}


def main():
    payload = event.read()
    if payload.get("stop_hook_active"):
        return
    # Grok also fires an observe-only Stop when the session closes.
    if payload["agent"] == "grok" and payload.get("reason") not in (None, "end_turn"):
        return
    # Codex and Grok pass the reply itself; Claude Code only points at its transcript.
    reply = payload.get("last_assistant_message") or last_reply(payload.get("transcript_path") or "")
    if len(reply.strip()) < 40:
        return
    rules = rules_for(reply)
    if not rules:
        jev.note("reply_check", "skipped", payload["agent"])
        return
    try:
        scores = judge(reply, rules)
    except jev.JevError:
        return
    broken = [name for name in rules if scores[name] >= BLOCK_AT]
    jev.note("reply_check", "blocked" if broken else "passed", payload["agent"], scores)
    if broken:
        print(json.dumps({
            "decision": "block",
            "reason": "doc: your last reply %s, which the user's rules forbid. %s" % (
                " and ".join("%s (%.2f)" % (RULES[name]["reason"], scores[name]) for name in broken),
                " ".join(RULES[name]["fix"] for name in broken)),
        }))


if __name__ == "__main__":
    main()
