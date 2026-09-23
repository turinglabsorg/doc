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
        decision, reasons = publish_guard.judge("See /Users/someone/work/log.txt for details")
        self.assertEqual(decision, "deny")
        self.assertIn("local paths", reasons[0])

    def test_attribution_is_denied(self):
        decision, _ = publish_guard.judge("Done.\n\nCo-Authored-By: Someone <x@y.z>")
        self.assertEqual(decision, "deny")

    def test_clean_text_passes_when_jev_is_down(self):
        decision, _ = publish_guard.judge("Parser now rejects empty input; covered by a new test.")
        self.assertEqual(decision, "allow")


class BothAgents(unittest.TestCase):
    def test_reply_from_codex_payload(self):
        from doc import reply_check
        seen = {}
        with mock.patch.object(reply_check, "judge", side_effect=lambda r: seen.setdefault("reply", r) and 0.0):
            with mock.patch("sys.stdin", io.StringIO(json.dumps({
                    "hook_event_name": "Stop", "turn_id": "t", "stop_hook_active": False,
                    "last_assistant_message": "A reply long enough to be judged by the check."}))):
                reply_check.main()
        self.assertEqual(seen["reply"], "A reply long enough to be judged by the check.")

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
            f.write('#!/bin/sh\necho called >> "$MARK"\ncat >/dev/null\n')
        os.chmod(fake, 0o755)

    def started_hush(self, hook, command):
        if os.path.exists(self.mark):
            os.remove(self.mark)
        payload = json.dumps({"tool_input": {"command": command}})
        env = dict(os.environ, PATH=self.dir + ":/usr/bin:/bin", HOME=self.dir, MARK=self.mark)
        hook_path = os.path.join(os.path.dirname(__file__), "..", "bin", "doc-hook")
        subprocess.run([hook_path, hook], input=payload.encode(), env=env, check=True, timeout=10)
        return os.path.exists(self.mark)

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


if __name__ == "__main__":
    unittest.main()
