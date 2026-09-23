"""Decide which agent should take a task: `oclaude` (a fast, cheap model) only
for mechanical, low-risk work the router is confident about; `claude` for
everything else, including whenever the router cannot answer.

Run as `python3 -m doc.route "<task>"`: prints the decision as one JSON line.
"""

import json
import sys

from doc import jev

CHEAP_AT = 0.7
RISK_AT = 0.3

KINDS = {
    "mechanical": "Well-specified edits needing little judgment: renames, formatting, boilerplate, "
                  "small scripts, docs or comment fixes, straightforward tests for existing code",
    "standard": "Ordinary feature or bug work that needs some judgment within one area of a codebase",
    "delicate": "Security, credentials, data or schema migrations, production or deployment changes, "
                "broad multi-file design, debugging an unknown cause, or anything hard to undo",
}


def decide(task):
    answers = jev.ask(
        {"task": task[:8000]},
        {
            "kind": jev.choice("What kind of software work does `task` ask for?", KINDS),
            "risky": jev.noul(
                "Does `task` touch production systems, deployments, credentials, secrets, "
                "payments, or data that could be lost?",
                yes="The task can affect production, secrets, money or data",
                no="The task stays within code or docs that can be safely redone",
            ),
        },
        purpose="route",
    )
    kind = answers["kind"]
    risky = answers["risky"]["noul"]
    cheap = kind["choice"] == "mechanical" and kind["confidence"] >= CHEAP_AT and risky < RISK_AT
    return {
        "target": "oclaude" if cheap else "claude",
        "kind": kind["choice"],
        "confidence": round(kind["confidence"], 2),
        "risky": round(risky, 2),
    }


def main():
    task = " ".join(sys.argv[1:]).strip()
    try:
        decision = decide(task) if task else {"target": "claude", "why": "no task"}
    except jev.JevError as error:
        decision = {"target": "claude", "why": "router unavailable: %s" % error}
    jev.note("route", decision["target"])
    print(json.dumps(decision))


if __name__ == "__main__":
    main()
