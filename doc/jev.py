"""Minimal TypeSafe System One client: stdlib only, so it runs on the host
and inside the scott container alike. The key comes from TYPESAFE_API_KEY,
which hush injects (`hush run --name TYPESAFE_API_KEY --env TYPESAFE_API_KEY`)."""

import json
import os
import ssl
import time
import urllib.error
import urllib.request

API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("DOC_JEV_MODEL", "jev-1.13.0")
USAGE_LOG = os.path.expanduser("~/.cache/doc/usage.jsonl")


class JevError(Exception):
    pass


def _ssl_context():
    # python.org builds on macOS ship without a CA bundle until their
    # certificate installer runs; fall back to the system one.
    ctx = ssl.create_default_context()
    paths = ssl.get_default_verify_paths()
    if not (paths.cafile and os.path.exists(paths.cafile)) and os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def ask(state, questions, timeout=10.0, purpose=""):
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set: run through hush")
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    request = urllib.request.Request(
        API,
        data=body,
        method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        raise JevError("HTTP %s" % error.code) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise JevError(str(error)) from None
    _log_usage(purpose, data.get("usage", {}), time.time() - started)
    return data["answers"]


def _log_usage(purpose, usage, seconds):
    try:
        os.makedirs(os.path.dirname(USAGE_LOG), exist_ok=True)
        with open(USAGE_LOG, "a") as log:
            log.write(json.dumps({
                "ts": int(time.time()),
                "purpose": purpose,
                "input_tokens": usage.get("input_tokens"),
                "ms": int(seconds * 1000),
            }) + "\n")
    except OSError:
        pass


def noul(instructions, yes=None, no=None):
    question = {"type": "noul", "instructions": instructions}
    if yes or no:
        question["criteria"] = {"true": yes or "Yes", "false": no or "No"}
    return question


def choice(instructions, options):
    return {"type": "choice", "instructions": instructions, "criteria": options}
