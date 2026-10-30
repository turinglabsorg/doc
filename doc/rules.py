"""Jev rules an owner sets without touching the code.

DOC_RULES names a JSON file that turns built-in Jev rules off and adds rules of
the owner's own. Cora writes it from its panel. Without the variable nothing
changes, so the owner's own coding agents keep every check. The exact rules in
code (local paths, attribution lines) are not Jev rules and stay on.

    {"off": ["process_log", "reply:effort"],
     "add": [{"key": "client_names", "on": ["reply", "comment"],
              "question": "Does it name a client company or a client's contact person?",
              "reason": "names a client", "fix": "Leave the client's name out.",
              "keywords": ["acme"], "threshold": 0.8}]}

A built-in rule is turned off by its key, for every kind of text it reads, or by
`reply:<key>` / `comment:<key>` for one kind. An added rule with `"enabled": false`
is kept but not asked. An added rule reads every text of its kind, or only those
holding one of its keywords. A file that cannot be read, or a rule that does not make sense, is left
out: a broken setting never stops a check that would otherwise run.

`python3 -m doc.rules` prints the built-in Jev rules, so a panel can list them;
`python3 -m doc.rules try` reads {"target", "text", "rule"} on stdin and prints Jev's
score for that one rule, so a rule can be tried before it is saved.
"""

import json
import os
import re
import sys

from doc import jev

# What each kind of text is, for Jev, under the name the checks give it.
TARGETS = {
    "reply": "a message an agent is about to send to people in a chat",
    "comment": "a comment an agent is about to publish on GitHub or Linear",
}
DEFAULT_THRESHOLD = 0.8
KEY = re.compile(r"[a-z][a-z0-9_]{0,40}")


def load():
    """The owner's settings: built-in rule keys turned off, and rules added."""
    settings = {"off": set(), "add": []}
    path = os.environ.get("DOC_RULES")
    if not path:
        return settings
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings
    settings["off"] = {key for key in data.get("off") or [] if isinstance(key, str)}
    builtin = {rule["key"] for rule in builtins()}
    for rule in data.get("add") or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        key = str(rule.get("key") or "")
        question = str(rule.get("question") or "").strip()[:1000]
        on = [target for target in rule.get("on") or [] if target in TARGETS]
        if not KEY.fullmatch(key) or key in builtin or not question or not on:
            continue
        threshold = rule.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.5 <= threshold <= 0.99:
            threshold = DEFAULT_THRESHOLD
        settings["add"].append({
            "key": key,
            "on": on,
            "question": question,
            "reason": str(rule.get("reason") or "breaks the rule \"%s\"" % key).strip()[:300],
            "fix": str(rule.get("fix") or "Rewrite it.").strip()[:300],
            "keywords": [str(word).strip().lower() for word in rule.get("keywords") or [] if str(word).strip()][:20],
            "threshold": float(threshold),
        })
    return settings


def is_off(settings, target, key):
    """Whether the owner turned the built-in rule `key` off for this kind of text."""
    return key in settings["off"] or "%s:%s" % (target, key) in settings["off"]


def added(target, text, settings):
    """The added rules for `target` that read `text`: all of them, or those whose keyword it holds."""
    lowered = text.lower()
    return [rule for rule in settings["add"]
            if target in rule["on"] and (not rule["keywords"] or any(word in lowered for word in rule["keywords"]))]


def question(rule, target):
    """An added rule as a Jev question about the text the check names `target`."""
    return jev.noul("Answer about `%s`, %s. %s" % (target, TARGETS[target], rule["question"]))


def builtins():
    """Every built-in Jev rule, with the kind of text it reads and why it stops one."""
    from doc import publish_guard, reply_check
    return ([{"key": key, "on": "reply", "reason": rule["reason"]} for key, rule in reply_check.RULES.items()]
            + [{"key": key, "on": "comment", "reason": publish_guard.REASONS[key]} for key in publish_guard.QUESTIONS])


def score(target, text, rule):
    """Jev's score for one rule, saved or not, on one text."""
    if target not in TARGETS:
        raise ValueError("unknown target")
    draft = {"question": str(rule.get("question") or "").strip()[:1000]}
    if not draft["question"]:
        raise ValueError("the rule has no question")
    answers = jev.ask({target: str(text)[:20000]}, {"rule": question(draft, target)}, purpose="rules_try")
    return answers["rule"]["noul"]


def main(argv):
    if argv[:1] != ["try"]:
        print(json.dumps(builtins()))
        return
    request = json.load(sys.stdin)
    try:
        print(json.dumps({"score": round(score(request.get("target"), request.get("text") or "", request.get("rule") or {}), 3)}))
    except (jev.JevError, ValueError, AttributeError) as error:
        print(json.dumps({"error": str(error)}))


if __name__ == "__main__":
    main(sys.argv[1:])
