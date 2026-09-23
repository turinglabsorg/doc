"""Integration tests against the live TypeSafe API. Run through hush:
hush run --name TYPESAFE_API_KEY --env TYPESAFE_API_KEY --redact -- python3 -m unittest"""
import os
import unittest

from doc import publish_guard, reply_check, route, skill_router

LIVE = bool(os.environ.get("TYPESAFE_API_KEY"))

SKILLS = [
    {"name": "grog-answer", "description": "Post a summary comment to a GitHub issue/PR or Linear issue.", "body": "Use grog answer <url> <file> to post the comment."},
    {"name": "devo", "description": "DevOps specialist for auditing GCP, AWS, and DigitalOcean environments: costs, logs, IAM, service state.", "body": "Use devo with a profile for every cloud call."},
    {"name": "hush", "description": "Agent-blind secrets. Ingest from Bitwarden by name, never print values, inject via hush run.", "body": "hush pull, hush run."},
    {"name": "frontend-design", "description": "Create distinctive, production-grade frontend interfaces and web components.", "body": "Design pages and components."},
]


@unittest.skipUnless(LIVE, "needs TYPESAFE_API_KEY (run through hush)")
class PublishGuard(unittest.TestCase):
    def assertBlocked(self, text):
        decision, reasons = publish_guard.judge(text)
        self.assertNotEqual(decision, "allow", "should not pass: %r" % text)

    def assertPasses(self, text):
        decision, reasons = publish_guard.judge(text)
        self.assertEqual(decision, "allow", "%r -> %s %s" % (text, decision, reasons))

    def test_clean_report_passes(self):
        self.assertPasses("Fixed in abc1234: the parser now rejects empty input instead of crashing. "
                          "Covered by a new unit test; CI is green.")

    def test_clean_report_italian_passes(self):
        self.assertPasses("Corretto: la validazione ora rifiuta le date nel passato. Verificato in staging, "
                          "la PR #42 è pronta per la review.")

    def test_local_state(self):
        self.assertBlocked("The fix is ready locally but not pushed yet; I'll push it after the review.")

    def test_local_state_italian(self):
        self.assertBlocked("La correzione è pronta in locale ma non è ancora stata pushata.")

    def test_effort_estimate(self):
        self.assertBlocked("This should take about three days of development to finish.")

    def test_process_log(self):
        self.assertBlocked("I retried the build three times, npm install failed twice, then I cleared "
                           "the cache, re-ran the command and it finally worked.")

    def test_billing(self):
        self.assertBlocked("Logged 2 billable hours on this issue.")


@unittest.skipUnless(LIVE, "needs TYPESAFE_API_KEY (run through hush)")
class ReplyCheck(unittest.TestCase):
    def test_effort_estimate_blocks(self):
        self.assertGreaterEqual(reply_check.judge(
            "Ci vorranno circa due giorni di sviluppo per completare la migrazione."), reply_check.BLOCK_AT)

    def test_process_duration_passes(self):
        self.assertLess(reply_check.judge(
            "Fatto: il build dell'immagine impiega circa 4 minuti e ora gira sul Mac Pro."), reply_check.BLOCK_AT)

    def test_plain_report_passes(self):
        self.assertLess(reply_check.judge(
            "The test passes and the commit is on main; the deploy finished at 14:02."), reply_check.BLOCK_AT)


@unittest.skipUnless(LIVE, "needs TYPESAFE_API_KEY (run through hush)")
class SkillRouter(unittest.TestCase):
    def test_comment_goes_to_grog_answer(self):
        self.assertEqual(skill_router.suggest(
            "Posta un riepilogo del lavoro come commento sulla issue https://github.com/o/r/issues/7", SKILLS),
            "grog-answer")

    def test_cloud_costs_go_to_devo(self):
        self.assertEqual(skill_router.suggest(
            "Controlla i costi di DigitalOcean del mese scorso per il progetto growfi", SKILLS), "devo")

    def test_general_question_needs_no_skill(self):
        self.assertIsNone(skill_router.suggest(
            "Che differenza c'è tra let e const in JavaScript?", SKILLS))


@unittest.skipUnless(LIVE, "needs TYPESAFE_API_KEY (run through hush)")
class Route(unittest.TestCase):
    def test_mechanical_goes_cheap(self):
        self.assertEqual(route.decide("Rename the variable foo to bar in utils.py")["target"], "oclaude")

    def test_production_migration_stays_on_claude(self):
        self.assertEqual(route.decide(
            "Write the migration that drops the users.email column in the production database")["target"], "claude")

    def test_unknown_bug_stays_on_claude(self):
        self.assertEqual(route.decide(
            "Figure out why the payment webhook sometimes fails in production")["target"], "claude")


if __name__ == "__main__":
    unittest.main()
