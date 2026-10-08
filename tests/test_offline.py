import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from doc import publish_guard


class ExtractText(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "notes.md"), "w") as f:
            f.write("From a file")

    def test_inline_body(self):
        self.assertEqual(publish_guard.extract_text('gh pr comment 12 --body "Fixed X"', self.dir), "Fixed X")

    def test_body_equals(self):
        self.assertEqual(publish_guard.extract_text("gh issue comment 3 --body='ok done'", self.dir), "ok done")

    def test_body_file(self):
        self.assertEqual(publish_guard.extract_text("gh issue comment 3 --body-file notes.md", self.dir), "From a file")

    def test_heredoc(self):
        command = "gh pr comment 5 --body-file - <<'EOF'\nline one\nline two\nEOF\n"
        self.assertEqual(publish_guard.extract_text(command, self.dir), "line one\nline two")

    def test_gh_api_field(self):
        command = 'gh api repos/o/r/issues/1/comments -f body="via api"'
        self.assertEqual(publish_guard.extract_text(command, self.dir), "via api")

    def test_grog_answer_through_node(self):
        command = "node ~/.codex/tools/grog/index.js answer https://github.com/acme/app/issues/3 notes.md"
        self.assertTrue(publish_guard.PUBLISHING.search(command))
        self.assertEqual(publish_guard.extract_text(command, self.dir), "From a file")

    def test_grog_answer_file(self):
        self.assertEqual(publish_guard.extract_text("grog answer https://x/1 notes.md", self.dir), "From a file")

    def test_only_publishing_commands_match(self):
        self.assertTrue(publish_guard.PUBLISHING.search("gh pr create --title t --body b"))
        self.assertTrue(publish_guard.PUBLISHING.search("grog answer https://x f.md"))
        self.assertFalse(publish_guard.PUBLISHING.search("gh pr view 12"))
        self.assertFalse(publish_guard.PUBLISHING.search("git commit -m 'gh pr comment'x"))
        self.assertFalse(publish_guard.PUBLISHING.search('echo "run gh pr comment later"'))
        self.assertTrue(publish_guard.PUBLISHING.search("cd repo && gh pr comment 3 --body x"))
        self.assertTrue(publish_guard.PUBLISHING.search("GH_TOKEN=x /usr/local/bin/gh issue comment 1 -b y"))


class ExactRulesWithoutJev(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_local_path_is_denied(self):
        decision, reasons, _ = publish_guard.judge("See /Users/someone/work/log.txt for details")
        self.assertEqual(decision, "deny")
        self.assertIn("local paths", reasons[0])

    def test_attribution_is_denied(self):
        decision, _, _ = publish_guard.judge("Done.\n\nCo-Authored-By: Someone <x@y.z>")
        self.assertEqual(decision, "deny")

    def test_clean_text_passes_when_jev_is_down(self):
        decision, _, _ = publish_guard.judge("Parser now rejects empty input; covered by a new test.")
        self.assertEqual(decision, "allow")


class BothAgents(unittest.TestCase):
    def test_reply_from_codex_payload(self):
        from doc import reply_check
        seen = {}
        reply = "A reply long enough to be judged: this takes about 2 days of work."
        with mock.patch.object(reply_check, "judge",
                               side_effect=lambda r, rules: seen.setdefault("reply", r) and {"effort": 0.0}), \
                mock.patch.object(reply_check.jev, "note"):
            with mock.patch("sys.stdin", io.StringIO(json.dumps({
                    "hook_event_name": "Stop", "turn_id": "t", "stop_hook_active": False,
                    "last_assistant_message": reply}))):
                reply_check.main()
        self.assertEqual(seen["reply"], reply)

    def test_reply_from_claude_transcript(self):
        from doc import reply_check
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        with open(path, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                    "content": [{"type": "text", "text": "Final answer from the transcript."}]}}) + "\n")
        self.assertEqual(reply_check.last_reply(path), "Final answer from the transcript.")

    def test_skill_dirs_follow_the_agent(self):
        from doc import skill_router
        codex = skill_router.skill_dirs({"turn_id": "t", "cwd": "/repo"})
        claude = skill_router.skill_dirs({"transcript_path": "/x/.claude/projects/p/s.jsonl", "cwd": "/repo"})
        self.assertTrue(any(d.endswith(".codex/skills") and not d.startswith("/repo") for d in codex))
        self.assertIn("/repo/.codex/skills", codex)
        self.assertTrue(any(d.endswith(".claude/skills") and not d.startswith("/repo") for d in claude))
        self.assertIn("/repo/.claude/skills", claude)
        self.assertFalse(any(".codex" in d for d in claude))


class HookWrapper(unittest.TestCase):
    """bin/doc-hook starts hush (and so Python and Jev) only when it has to."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.mark = os.path.join(self.dir, "called")
        fake = os.path.join(self.dir, "hush")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "$@" >> "$MARK"\ncat >/dev/null\n')
        os.chmod(fake, 0o755)

    def hush_args(self, hook, payload, **env):
        """The arguments hush was started with, or None if it was not."""
        if os.path.exists(self.mark):
            os.remove(self.mark)
        env = dict({k: v for k, v in os.environ.items() if not k.startswith("DOC_")},
                   PATH=self.dir + ":/usr/bin:/bin", HOME=self.dir, MARK=self.mark, **env)
        hook_path = os.path.join(os.path.dirname(__file__), "..", "bin", "doc-hook")
        subprocess.run([hook_path, hook], input=json.dumps(payload).encode(), env=env, check=True, timeout=10)
        if not os.path.exists(self.mark):
            return None
        with open(self.mark) as f:
            return f.read().splitlines()

    def started_hush(self, hook, command):
        return self.hush_args(hook, {"tool_input": {"command": command}}) is not None

    def test_ordinary_commands_skip_hush(self):
        for command in ["ls -la", "npm test", "gh api repos/acme/app/pulls", "gh pr view 3",
                        "gh issue list --state open"]:
            with self.subTest(command=command):
                self.assertFalse(self.started_hush("publish_guard", command))

    def test_publishing_commands_reach_the_check(self):
        for command in ['gh pr comment 12 --body "Fixed"', 'cd app\ngh issue create --title T --body B',
                        "gh api repos/acme/app/issues/3/comments -f body=hi", "grog answer https://x y.md",
                        "node ~/.codex/tools/grog/index.js answer https://x y.md"]:
            with self.subTest(command=command):
                self.assertTrue(self.started_hush("publish_guard", command))

    def test_other_hooks_always_run(self):
        self.assertTrue(self.started_hush("skill_router", "anything"))

    def test_grok_publishing_command_reaches_the_check(self):
        payload = {"hookEventName": "pre_tool_use", "hook_event_name": "PreToolUse", "sessionId": "s",
                   "toolName": "run_terminal_command", "toolInput": {"command": 'gh pr comment 3 --body "x"'}}
        self.assertIsNotNone(self.hush_args("publish_guard", payload))

    def test_grok_prompts_skip_the_router(self):
        payload = {"hookEventName": "user_prompt_submit", "hook_event_name": "UserPromptSubmit",
                   "sessionId": "s", "prompt": "check the cloud costs for last month please"}
        self.assertIsNone(self.hush_args("skill_router", payload))
        self.assertIsNone(self.hush_args("skill_router", dict(payload, prompt="explain \"hookEventName\" in grok")))
        self.assertIsNotNone(self.hush_args("skill_router", {"session_id": "s", "hook_event_name": "UserPromptSubmit",
                                                             "prompt": 'explain "hookEventName" in grok'}))

    def test_hermes_prompts_reach_the_router(self):
        payload = {"hook_event_name": "pre_llm_call", "session_id": "h", "extra": {"user_message": "check costs"}}
        self.assertIsNotNone(self.hush_args("skill_router", payload))

    def test_doc_settings_cross_hush(self):
        args = self.hush_args("reply_check", {"session_id": "s"}, DOC_USAGE_LOG="/x/usage log.jsonl",
                              DOC_JEV_MODEL="jev-test")
        self.assertIn("DOC_USAGE_LOG=/x/usage log.jsonl", args)
        self.assertIn("DOC_JEV_MODEL=jev-test", args)
        self.assertFalse(any(a.startswith("DOC_SKILL_SEEN_DIR") for a in args))
        self.assertEqual(args[args.index("--") + 1], "env")


def _rank(probabilities, needs):
    return {"best": {"choice": max(probabilities, key=probabilities.get), "probabilities": probabilities,
                     "confidence": max(probabilities.values())}, "needs": {"noul": needs}}


class Economy(unittest.TestCase):
    """Jev is asked only when its answer can change what the agent sees."""

    SKILLS = [{"name": n, "description": n + " skill", "body": ""} for n in ("hush", "devo", "grog-talk")]

    def test_confident_ranking_answers_with_one_request(self):
        from doc import skill_router
        with mock.patch.object(skill_router.jev, "ask", side_effect=[_rank({"hush": 0.9, "devo": 0.05, "none": 0.05}, 0.9)]) as ask:
            self.assertEqual(skill_router.suggest("put the master keys in hush", self.SKILLS)[0], "hush")
        self.assertEqual(ask.call_count, 1)

    def test_unsure_ranking_is_verified(self):
        from doc import skill_router
        answers = [_rank({"devo": 0.6, "hush": 0.2, "none": 0.2}, 0.7), {"fit_0": {"noul": 0.8}, "fit_1": {"noul": 0.1}, "fit_2": {"noul": 0.0}}]
        with mock.patch.object(skill_router.jev, "ask", side_effect=answers) as ask:
            self.assertEqual(skill_router.suggest("did the cloud logins break?", self.SKILLS)[0], "devo")
        self.assertEqual(ask.call_count, 2)

    def test_weak_ranking_stops_after_one_request(self):
        from doc import skill_router
        with mock.patch.object(skill_router.jev, "ask", side_effect=[_rank({"devo": 0.2, "none": 0.8}, 0.6)]) as ask:
            self.assertIsNone(skill_router.suggest("are we done yet?", self.SKILLS)[0])
        self.assertEqual(ask.call_count, 1)

    def test_a_top_skill_already_suggested_needs_no_verify(self):
        from doc import skill_router
        with mock.patch.object(skill_router.jev, "ask", side_effect=[_rank({"devo": 0.6, "hush": 0.2, "none": 0.2}, 0.7)]) as ask:
            name, scores = skill_router.suggest("and the logs of that service?", self.SKILLS, seen={"devo"})
        self.assertEqual((name, ask.call_count), ("devo", 1))
        self.assertEqual(scores, {"needs": 0.7, "top": 0.6})

    def test_harness_texts_never_reach_jev(self):
        from doc import skill_router
        for prompt in ["Stop hook feedback: task #3 remains unresolved and more", "This session is being continued from a previous conversation",
                       "<task-notification>done</task-notification> and more text"]:
            with mock.patch.object(skill_router, "suggest", side_effect=AssertionError("asked Jev")), \
                    mock.patch("sys.stdin", io.StringIO(json.dumps({"prompt": prompt, "session_id": "s"}))):
                skill_router.main()

    def test_a_skill_is_suggested_once_per_session(self):
        from doc import skill_router
        seen = tempfile.mkdtemp()
        outputs = []
        for _ in range(2):
            with mock.patch.object(skill_router, "SEEN_DIR", seen), \
                    mock.patch.object(skill_router, "load_skills", return_value=self.SKILLS), \
                    mock.patch.object(skill_router, "suggest", return_value=("hush", {})), \
                    mock.patch.object(skill_router.jev, "note"), \
                    mock.patch("sys.stdin", io.StringIO(json.dumps({"prompt": "here is the key for the service", "session_id": "abc"}))), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                skill_router.main()
                outputs.append(out.getvalue())
        self.assertIn("hush", outputs[0])
        self.assertEqual(outputs[1], "")

    def test_replies_without_durations_skip_jev(self):
        from doc import reply_check
        for reply in ["Tests pass and the branch is merged; the report is on the issue.",
                      "La build è verde, ho aggiornato il README e aperto la PR su GitHub."]:
            self.assertIsNone(reply_check.DURATION.search(reply), reply)

    def test_estimates_reach_jev(self):
        from doc import reply_check
        for reply in ["Questa modifica richiede circa tre giorni di sviluppo.", "It will take about 2 hours.",
                      "Ci vogliono un paio di giorni.", "Stima: mezza giornata di lavoro.", "Should be done in 3-4 days.",
                      "A few days of work at most."]:
            self.assertIsNotNone(reply_check.DURATION.search(reply), reply)


class Grok(unittest.TestCase):
    """Grok runs the Claude Code hooks with a camelCase payload."""

    def run_main(self, module, payload):
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            module.main()
        return out.getvalue()

    def test_payload_is_read_in_one_shape(self):
        from doc import event
        payload = event.read(io.StringIO(json.dumps({"hookEventName": "stop", "hook_event_name": "Stop",
                                                     "sessionId": "g1", "stopHookActive": True,
                                                     "lastAssistantMessage": "done"})))
        self.assertEqual((payload["agent"], payload["session_id"], payload["stop_hook_active"],
                          payload["last_assistant_message"]), ("grok", "g1", True, "done"))
        self.assertEqual(event.agent({"turn_id": "t"}), "codex")
        self.assertEqual(event.agent({"session_id": "c", "transcript_path": "/x/.claude/p.jsonl"}), "claude")

    def test_publish_guard_checks_grok_commands(self):
        payload = {"hookEventName": "pre_tool_use", "hook_event_name": "PreToolUse", "sessionId": "g",
                   "toolName": "run_terminal_command",
                   "toolInput": {"command": 'gh pr comment 3 --body "See /Users/me/x.log"'}}
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                mock.patch.object(publish_guard.jev, "note") as note:
            out = json.loads(self.run_main(publish_guard, payload))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(note.call_args[0][:3], ("publish_guard", "deny", "grok"))

    def test_reply_check_reads_grok_reply(self):
        from doc import reply_check
        reply = "Ci vorranno circa tre giorni di sviluppo per finire la migrazione del database."
        payload = {"hookEventName": "stop", "hook_event_name": "Stop", "sessionId": "g", "reason": "end_turn",
                   "stopHookActive": False, "lastAssistantMessage": reply}
        with mock.patch.object(reply_check, "judge", return_value={"effort": 0.95}) as judge, \
                mock.patch.object(reply_check.jev, "note"):
            out = json.loads(self.run_main(reply_check, payload))
        self.assertEqual(judge.call_args[0], (reply, ["effort"]))
        self.assertEqual(out["decision"], "block")
        for extra in ({"stopHookActive": True}, {"reason": "shutdown"}, {"reason": "channel_closed"}):
            with mock.patch.object(reply_check, "judge", side_effect=AssertionError("asked Jev")):
                self.assertEqual(self.run_main(reply_check, dict(payload, **extra)), "")

    def test_skill_router_never_asks_under_grok(self):
        from doc import skill_router
        payload = {"hookEventName": "user_prompt_submit", "hook_event_name": "UserPromptSubmit",
                   "sessionId": "g", "prompt": "check the cloud costs of last month for acme"}
        with mock.patch.object(skill_router, "suggest", side_effect=AssertionError("asked Jev")):
            self.assertEqual(self.run_main(skill_router, payload), "")


class Hermes(unittest.TestCase):
    """Hermes runs the hooks in ~/.hermes/config.yaml with its own events and answers."""

    def run_main(self, module, payload):
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            module.main()
        return out.getvalue()

    def payload(self, event, **extra):
        return {"hook_event_name": event, "tool_name": None, "tool_input": None, "session_id": "h1",
                "cwd": "/repo", "profile": "default", "extra": extra}

    def test_payload_is_read_in_one_shape(self):
        from doc import event
        read = lambda p: event.read(io.StringIO(json.dumps(p)))
        prompt = read(self.payload("pre_llm_call", user_message="check the cloud costs", is_first_turn=True))
        self.assertEqual((prompt["agent"], prompt["prompt"]), ("hermes", "check the cloud costs"))
        stop = read(self.payload("pre_verify", final_response="Done.", attempt=0))
        self.assertEqual((stop["last_assistant_message"], stop["stop_hook_active"]), ("Done.", False))
        self.assertTrue(read(self.payload("pre_verify", final_response="Done.", attempt=1))["stop_hook_active"])

    def test_publish_guard_answers_in_hermes_shape(self):
        payload = dict(self.payload("pre_tool_call"), tool_name="terminal",
                       tool_input={"command": 'gh pr comment 3 --body "See /Users/me/x.log"'})
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                mock.patch.object(publish_guard.jev, "note") as note:
            out = json.loads(self.run_main(publish_guard, payload))
        self.assertEqual(out["decision"], "block")
        self.assertIn("local paths", out["reason"])
        self.assertEqual(note.call_args[0][2], "hermes")
        with mock.patch.object(publish_guard, "judge", return_value=("ask", ["borderline"], {})), \
                mock.patch.object(publish_guard.jev, "note"):
            out = json.loads(self.run_main(publish_guard, payload))
        self.assertEqual(out["action"], "approve")
        self.assertIn("borderline", out["message"])

    def test_skill_router_answers_with_context(self):
        from doc import skill_router
        seen = tempfile.mkdtemp()
        with mock.patch.object(skill_router, "SEEN_DIR", seen), \
                mock.patch.object(skill_router, "load_skills", return_value=Economy.SKILLS), \
                mock.patch.object(skill_router, "suggest", return_value=("devo", {})) as suggest, \
                mock.patch.object(skill_router.jev, "note"):
            out = json.loads(self.run_main(skill_router, self.payload(
                "pre_llm_call", user_message="check the cloud costs of last month for acme")))
        self.assertEqual(suggest.call_args[0][0], "check the cloud costs of last month for acme")
        self.assertIn("devo", out["context"])
        self.assertEqual(set(out), {"context"})
        dirs = skill_router.skill_dirs(self.payload("pre_llm_call"))
        self.assertTrue(any(d.endswith(".hermes/skills") and not d.startswith("/repo") for d in dirs))
        self.assertIn("/repo/.agents/skills", dirs)

    def test_reply_check_keeps_hermes_working(self):
        from doc import reply_check
        reply = "Ci vorranno circa tre giorni di sviluppo per finire la migrazione del database."
        with mock.patch.object(reply_check, "judge", return_value={"effort": 0.95}), \
                mock.patch.object(reply_check.jev, "note"):
            out = json.loads(self.run_main(reply_check, self.payload("pre_verify", final_response=reply, attempt=0)))
        self.assertEqual(out["decision"], "block")
        with mock.patch.object(reply_check, "judge", side_effect=AssertionError("asked Jev")):
            self.assertEqual(self.run_main(reply_check, self.payload("pre_verify", final_response=reply, attempt=1)), "")


class SecretRequests(unittest.TestCase):
    def test_replies_naming_a_secret_reach_jev(self):
        from doc import reply_check
        for reply in ["Incollami qui il token di GitHub e procedo.", "Please paste your API key in the chat.",
                      "Qual è la password del database?", "Mandami la chiave API di Stripe.",
                      "I need the access key for the bucket."]:
            self.assertEqual(reply_check.rules_for(reply), ["secret_request"], reply)

    def test_ordinary_replies_skip_jev(self):
        from doc import reply_check
        for reply in ["Il punto chiave è la cache: ora i test passano.", "The parser now rejects empty input."]:
            self.assertEqual(reply_check.rules_for(reply), [], reply)

    def test_both_rules_go_in_one_request(self):
        from doc import reply_check
        reply = "Mandami il token in chat e in due giorni di lavoro chiudiamo la migrazione."
        with mock.patch.object(reply_check.jev, "ask", return_value={"effort": {"noul": 0.9},
                                                                     "secret_request": {"noul": 0.95}}) as ask, \
                mock.patch.object(reply_check.jev, "note") as note, \
                mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "c", "last_assistant_message": reply}))), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            reply_check.main()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(set(ask.call_args[0][1]), {"effort", "secret_request"})
        reason = json.loads(out.getvalue())["reason"]
        self.assertIn("effort or time estimate", reason)
        self.assertIn("hush", reason)
        self.assertEqual(note.call_args[0][3], {"effort": 0.9, "secret_request": 0.95})


class Outcomes(unittest.TestCase):
    def test_note_records_the_decision_only(self):
        from doc import jev
        log = os.path.join(tempfile.mkdtemp(), "usage.jsonl")
        with mock.patch.object(jev, "USAGE_LOG", log):
            jev.note("reply_check", "passed")
        import json
        entry = json.loads(open(log).read())
        self.assertEqual((entry["purpose"], entry["outcome"]), ("reply_check", "passed"))
        self.assertEqual(set(entry), {"ts", "purpose", "outcome"})

    def test_note_records_agent_and_scores_but_no_text(self):
        from doc import jev
        log = os.path.join(tempfile.mkdtemp(), "usage.jsonl")
        with mock.patch.object(jev, "USAGE_LOG", log):
            jev.note("publish_guard", "ask", "grok", {"effort": 0.61234, "comment": "some text", "flag": True})
        entry = json.loads(open(log).read())
        self.assertEqual(entry["agent"], "grok")
        self.assertEqual(entry["scores"], {"effort": 0.612})


if __name__ == "__main__":
    unittest.main()
