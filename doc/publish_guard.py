"""PreToolUse (Bash): check a GitHub or Linear comment before it is published.

Code finds the publishing commands and the text they would post, and checks the
exact rules (local paths, attribution lines). Jev judges the rules that need
reading: local-only state, effort estimates, the agent's own process, billing.
A clear violation is denied with the reasons, so the agent rewrites the text; a
borderline one asks the user. If Jev is unavailable the exact rules still apply.
"""

import json
import os
import re
import shlex
import sys

from doc import jev

# A publishing command in command position: at the start of a line or after
# ; & | ( — optionally behind VAR=value assignments or a path — so a mention
# inside another command's string (a commit message, an echo) is not one.
# grog also runs as `node <tools>/grog/index.js`, which is how the grog skills
# call it.
PUBLISHING = re.compile(
    r"(?:^|[;&|(\n])\s*(?:\w+=\S*\s+)*(?:\S*/)?"
    r"(?:gh\s+(?:issue|pr)\s+(?:comment|create|edit|review)"
    r"|gh\s+api\b[^|;&\n]*\bcomments?\b"
    r"|(?:node\s+\S*/)?grog(?:/index\.js)?\s+(?:answer|create|update))\b"
)
TEXT_FLAGS = {"--body", "-b", "--description"}
FILE_FLAGS = {"--body-file", "-F", "--description-file"}
LOCAL_PATH = re.compile(r"(?<![\w.])(?:/Users/|/home/|/private/|/var/folders/|/tmp/)[^\s)\"'`]+")
ATTRIBUTION = re.compile(r"Co-Authored-By:|Generated with \[?Claude Code", re.IGNORECASE)
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\s*(?:\n|$)", re.DOTALL)

DENY_AT = 0.8
ASK_AT = 0.55

QUESTIONS = {
    "local_state": jev.noul(
        "Does `comment` say that code or work exists only locally: not pushed, waiting to be "
        "pushed, sitting in a worktree, or ahead of the remote?",
        yes="The comment reports local-only, unpushed or not-yet-pushed state",
        no="The comment does not describe local-only or unpushed state",
    ),
    "effort": jev.noul(
        "Does `comment` estimate how much time or effort some work takes or took, such as "
        "hours or days of development, or how long something will take to build?",
        yes="A work-effort or development-time estimate appears",
        no="No work-effort estimate; runtimes of processes and dates do not count",
    ),
    "process_log": jev.noul(
        "Does `comment` narrate the author's own working process: retries, transient tool "
        "errors, shell commands that were run, environment setup, or cleanup steps?",
        yes="The comment reads like an activity log of how the work was done",
        no="The comment reports results, causes, behavior or decisions, not the process",
    ),
    "billing": jev.noul(
        "Does `comment` mention billable hours, logged time, time tracking or invoicing?",
        yes="Billing or time-tracking is mentioned",
        no="No billing or time-tracking content",
    ),
}
REASONS = {
    "local_state": "it describes local or unpushed state",
    "effort": "it contains an effort or time estimate",
    "process_log": "it narrates the process (retries, commands, setup) instead of results",
    "billing": "it mentions billable hours or time tracking",
}


def extract_text(command, cwd):
    """Return the text a publishing command would post, or None if unknown."""
    heredoc = HEREDOC.search(command)
    first_line = command.split("\n", 1)[0]
    try:
        words = shlex.split(first_line)
    except ValueError:
        return heredoc.group(2) if heredoc else None
    for i, word in enumerate(words):
        name, _, inline = word.partition("=")
        value = inline if inline else (words[i + 1] if i + 1 < len(words) else "")
        if name in TEXT_FLAGS:
            return value
        if name in FILE_FLAGS:
            if value == "-":
                return heredoc.group(2) if heredoc else None
            return _read(value, cwd)
        if word in ("-f", "--raw-field", "--field") and i + 1 < len(words):
            key, _, field_value = words[i + 1].partition("=")
            if key == "body":
                if field_value.startswith("@"):
                    return _read(field_value[1:], cwd)
                return field_value
    for i, word in enumerate(words[:-2]):
        if word == "answer" and i and re.search(r"grog(?:/index\.js)?$", words[i - 1]):
            return _read(words[i + 2], cwd)
    return heredoc.group(2) if heredoc else None


def _read(path, cwd):
    try:
        with open(os.path.join(cwd or ".", os.path.expanduser(path)), encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def judge(text):
    """Return (decision, reasons) for a comment: allow, ask or deny."""
    reasons = []
    paths = LOCAL_PATH.findall(text)
    if paths:
        reasons.append("it contains local paths (%s)" % ", ".join(sorted(set(paths))[:3]))
    if ATTRIBUTION.search(text):
        reasons.append("it contains an attribution/co-author line")
    hard = bool(reasons)
    worst = 0.0
    try:
        answers = jev.ask({"comment": text[:20000]}, QUESTIONS, purpose="publish_guard")
        for key, answer in answers.items():
            value = answer["noul"]
            if value >= ASK_AT:
                reasons.append("%s (%.2f)" % (REASONS[key], value))
                worst = max(worst, value)
    except jev.JevError:
        pass
    if hard or worst >= DENY_AT:
        return "deny", reasons
    if worst >= ASK_AT:
        return "ask", reasons
    return "allow", reasons


def main():
    payload = json.load(sys.stdin)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not PUBLISHING.search(command):
        return
    text = extract_text(command, payload.get("cwd"))
    if not text or not text.strip():
        return
    decision, reasons = judge(text)
    jev.note("publish_guard", decision)
    if decision == "allow":
        return
    message = "doc: this comment breaks the publishing rules: " + "; ".join(reasons) + "."
    if decision == "deny":
        message += " Rewrite it to report only impact, root cause, behavior, verified results and remote links."
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": message,
    }}))


if __name__ == "__main__":
    main()
