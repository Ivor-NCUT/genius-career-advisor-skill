#!/usr/bin/env python3
"""The workbench job list and Grok Bot referral commands must refuse."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS = (
    "fanhan_open_jobs.py",
    "grok_bot_referral.py",
    "workbench_client.py",
)
MESSAGE = "不再读取或投递工作台岗位"


class RemovedPathTests(unittest.TestCase):
    def test_commands_refuse_without_network_clients(self):
        for name in SCRIPTS:
            script = ROOT / name
            source = script.read_text(encoding="utf-8")
            self.assertNotIn("urlopen", source)
            self.assertNotIn("FANHAN_GROK_BOT_WEBHOOK_URL", source)
            self.assertNotIn("FANHAN_PUBLIC_JOBS_URL", source)
            completed = subprocess.run(
                [sys.executable, str(script), "submit"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertIn(MESSAGE, completed.stderr)
            self.assertNotIn("http", completed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
