#!/usr/bin/env python3
"""The fanhan job list and Grok Bot referral are no longer part of the skill."""

import unittest
from pathlib import Path

import profile_status

ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    "scripts/fanhan_open_jobs.py",
    "scripts/grok_bot_referral.py",
    "scripts/test_grok_bot_referral.py",
    "scripts/workbench_client.py",
    "references/grok-bot-referral.md",
    "references/workbench-public-api.md",
)


class RemovedReferralTest(unittest.TestCase):
    def test_referral_entry_points_are_gone(self):
        for relative in REMOVED:
            self.assertFalse((ROOT / relative).exists(), relative)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        for text in (skill, prompt):
            self.assertNotIn("fanhan_open_jobs.py", text)
            self.assertNotIn("grok_bot_referral.py", text)
            self.assertNotIn("把材料交给泛函", text)
        result = profile_status.evaluate({"schema_version": "fanhan-career-profile-v1"}, ROOT)
        self.assertNotIn("ingest_ready", result)
        self.assertNotIn("missing_for_ingest", result)
        self.assertTrue((ROOT / "scripts/confirmation_gate.py").is_file())


if __name__ == "__main__":
    unittest.main()
