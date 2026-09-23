"""UserPromptSubmit: point the agent at the one skill that fits the turn, if any.

Two Jev requests, as in TypeSafe's skill-suggestion cookbook: the first ranks
every skill against the request and asks whether a skill is needed at all; the
second re-reads the top three with their full description and the opening of
their instructions, and may reject all of them. The winner becomes one line of
context the agent is free to ignore. Any failure adds nothing.
"""

import glob
import json
import os
import re
import sys

from doc import jev

SKILL_DIRS = ["~/.claude/skills", "~/.agents/skills"]
FIT_AT = 0.6
TOP = 3


def load_skills(cwd):
    roots = [os.path.expanduser(d) for d in SKILL_DIRS]
    if cwd:
        roots.append(os.path.join(cwd, ".claude", "skills"))
    skills = {}
    for root in roots:
        for path in sorted(glob.glob(os.path.join(root, "*", "SKILL.md"))):
            meta, body = _parse(path)
            name = meta.get("name") or os.path.basename(os.path.dirname(path))
            if name and name not in skills and meta.get("description"):
                skills[name] = {"name": name, "description": meta["description"], "body": body}
    return list(skills.values())


def _parse(path):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return {}, ""
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("name", "description"):
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, match.group(2)


def suggest(prompt, skills):
    options = {s["name"]: s["description"][:400] for s in skills}
    options["none"] = "No listed skill is meant for this request"
    ranked = jev.ask(
        {"request": prompt[:6000], "skills": [{"name": s["name"], "description": s["description"][:400]} for s in skills]},
        {
            "best": jev.choice("Which skill in `skills` is meant for handling `request`?", options),
            "needs": jev.noul(
                "Does handling `request` require one of the capabilities described in `skills`?",
                yes="The request asks for work that a listed skill is described as doing",
                no="The request can be handled without any of the listed skills",
            ),
        },
        purpose="skill_rank",
    )
    probabilities = ranked["best"]["probabilities"]
    candidates = [name for name, _ in sorted(probabilities.items(), key=lambda kv: -kv[1])
                  if name != "none"][:TOP]
    if ranked["needs"]["noul"] < 0.5 and ranked["best"]["choice"] == "none":
        return None
    by_name = {s["name"]: s for s in skills}
    detailed = [{"name": n, "description": by_name[n]["description"],
                 "instructions": by_name[n]["body"][:1500]} for n in candidates]
    fits = jev.ask(
        {"request": prompt[:6000], "candidates": detailed},
        {
            "fit_%d" % i: jev.noul(
                "Is `candidates[%d]` the skill that should handle `request`?" % i,
                yes="This skill's purpose matches what the request asks for",
                no="This skill is not meant for this request",
            )
            for i in range(len(detailed))
        },
        purpose="skill_verify",
    )
    scored = sorted(((fits["fit_%d" % i]["noul"], n) for i, n in enumerate(candidates)), reverse=True)
    if scored and scored[0][0] >= FIT_AT:
        return scored[0][1]
    return None


def main():
    payload = json.load(sys.stdin)
    prompt = (payload.get("prompt") or "").strip()
    if len(prompt) < 20 or prompt.startswith("/"):
        return
    skills = load_skills(payload.get("cwd"))
    if not skills:
        return
    try:
        name = suggest(prompt, skills)
    except (jev.JevError, KeyError):
        return
    if not name:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "<skill_relevance>\nRelevant to the current request: %s. Ignore this "
                             "if it does not fit what the user actually asked for.\n</skill_relevance>" % name,
    }}))


if __name__ == "__main__":
    main()
