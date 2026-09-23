import os
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
