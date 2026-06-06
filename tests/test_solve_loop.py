"""End-to-end test of the platform-driven solver worker (no real AI CLI, no
network). A stub runner script emits a flag; a fake platform accepts it."""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import orchestrator  # noqa: E402
from platforms.base import BasePlatform, NormalizedChallenge, SubmitResult  # noqa: E402

REPO = Path(orchestrator.__file__).resolve().parent


class FakePlatform(BasePlatform):
    name = "htb_ctf"

    def __init__(self):
        self.submitted = []

    def list_challenges(self):
        return [self._chall()]

    def get_challenge(self, challenge_id):
        return self._chall()

    def _chall(self):
        return NormalizedChallenge(
            platform="htb_ctf", event_id="ev", challenge_id="misc-1", name="Echo",
            category="Misc", points=100, description="d", target_kind="static",
        )

    def download_files(self, challenge, dest_dir):
        return []

    def submit_flag(self, challenge, flag):
        self.submitted.append(flag)
        return SubmitResult(accepted=(flag == "HTB{correct}"), message="ok", raw={"correct": flag == "HTB{correct}"})


class TestSolveLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Stub runner prints a flag (after a marker so clean_model_output keeps it).
        self.runner = self.root / "echo_runner.sh"
        self.runner.write_text("#!/usr/bin/env bash\necho '--- output begins ---'\necho 'HTB{correct}'\n")
        self.runner.chmod(self.runner.stat().st_mode | stat.S_IEXEC)
        # Prompt template (reuse repo's misc template).
        self.config = {
            "workspace": {"root": str(self.root / "challenges")},
            "routing": {"misc": "gemini"},
            "models": {"gemini": {"runner": f"bash {self.runner}", "prompt_template": "prompts/misc.txt"}},
            "ctf": {
                "flag_patterns": [r"(?<![A-Za-z])HTB\{[^}\n\r]{1,300}\}"],
                "max_agent_rounds": 2, "max_idle_rounds": 5, "model_timeout": 30,
            },
            "htb": {},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_worker_submits_and_solves(self):
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        chall = platform.get_challenge("misc-1")
        res = orchestrator.process_challenge(
            chall, self.config, db, platform, REPO,
            submit_mode="auto", auto_start=False, max_wrong=3,
        )
        self.assertEqual(res["status"], "solved")
        self.assertIn("HTB{correct}", platform.submitted)
        self.assertIn("misc-1", [str(x) for x in db.data["solved_ids"]])

    def test_no_submit_mode_does_not_submit(self):
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        chall = platform.get_challenge("misc-1")
        res = orchestrator.process_challenge(
            chall, self.config, db, platform, REPO,
            submit_mode="none", auto_start=False,
        )
        self.assertEqual(res["status"], "done")
        self.assertEqual(platform.submitted, [])


if __name__ == "__main__":
    unittest.main()
