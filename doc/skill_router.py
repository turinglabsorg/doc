"""UserPromptSubmit: point the agent at the one skill that fits the turn, if any.

As in TypeSafe's skill-suggestion cookbook, the first Jev request ranks every
skill against the request and asks whether a skill is needed at all. When that
ranking is already sure, its top skill is the answer; when it points at a skill
without being sure, a second request re-reads the top three with their full
description and the opening of their instructions, and may reject all of them;
otherwise nothing is suggested. The winner becomes one line of context the agent
is free to ignore, once per session. Texts the harness writes itself (stop-hook
feedback, compaction summaries) are not requests and never reach Jev. Any
failure adds nothing.
"""

import glob
import json
import os
import re
import sys

from doc import jev

# Chosen on 120 real prompts labelled by hand (2026-09-23): 21 right, 2 wrong,
# 6 missed, 127 Jev requests, against 20 / 9 / 7 / 173 for the previous flow
# (always verify, fit >= 0.6). The verify step under-rates skills the ranking
# is sure about, hence the direct path.
TOP_MIN = 0.3        # below this the ranking points at no skill: stop
NEEDS_MIN = 0.5      # "needs a listed skill" below this: stop
DIRECT_AT = 0.85     # ranking this sure (and needs >= DIRECT_NEEDS): answer
DIRECT_NEEDS = 0.8
FIT_AT = 0.7         # verify step threshold
TOP = 3

# Texts the harness writes into the user turn itself, not requests.
AUTOMATIC = ("<", "Stop hook feedback:", "This session is being continued", "A session-scoped Stop hook",
             "[Your previous response", "Caveat:")
SEEN_DIR = os.path.expanduser(os.environ.get("DOC_SKILL_SEEN_DIR", "~/.cache/doc/skill-router"))


def is_codex(payload):
    # Codex hook payloads carry a turn_id, and its transcripts live under ~/.codex.
    return "turn_id" in payload or "/.codex/" in (payload.get("transcript_path") or "")


def skill_dirs(payload):
    """Where the agent running this hook keeps its skills: user-level, shared, project."""
    if is_codex(payload):
        home = os.environ.get("CODEX_HOME") or "~/.codex"
        user, local = [os.path.join(home, "skills"), "~/.agents/skills"], [".codex/skills", ".agents/skills"]
    else:
        user, local = ["~/.claude/skills", "~/.agents/skills"], [".claude/skills"]
    roots = [os.path.expanduser(d) for d in user]
    cwd = payload.get("cwd")
    if cwd:
        roots += [os.path.join(cwd, d) for d in local]
    return roots


def load_skills(roots):
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
    needs = ranked["needs"]["noul"]
    ranking = sorted(((p, n) for n, p in ranked["best"]["probabilities"].items() if n != "none"), reverse=True)
    if not ranking or ranking[0][0] < TOP_MIN or needs < NEEDS_MIN:
        return None
    if ranking[0][0] >= DIRECT_AT and needs >= DIRECT_NEEDS:
        return ranking[0][1]
    candidates = [name for _, name in ranking[:TOP]]
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


def _seen_path(payload):
    session = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("session_id") or ""))
    return os.path.join(SEEN_DIR, session) if session else None


def already_suggested(payload, name):
    path = _seen_path(payload)
    try:
        with open(path, encoding="utf-8") as handle:
            return name in handle.read().split()
    except (OSError, TypeError):
        return False


def remember(payload, name):
    path = _seen_path(payload)
    if not path:
        return
    try:
        os.makedirs(SEEN_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(name + "\n")
    except OSError:
        pass


def main():
    payload = json.load(sys.stdin)
    prompt = (payload.get("prompt") or "").strip()
    if len(prompt) < 20 or prompt.startswith(("/",) + AUTOMATIC):
        return
    skills = load_skills(skill_dirs(payload))
    if not skills:
        return
    try:
        name = suggest(prompt, skills)
    except (jev.JevError, KeyError):
        return
    if name and already_suggested(payload, name):
        jev.note("skill_router", "repeat:%s" % name)
        return
    jev.note("skill_router", "suggested:%s" % name if name else "none")
    if not name:
        return
    remember(payload, name)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "<skill_relevance>\nRelevant to the current request: %s. Ignore this "
                             "if it does not fit what the user actually asked for.\n</skill_relevance>" % name,
    }}))


if __name__ == "__main__":
    main()
