"""End-to-end test of the platform-driven solver worker (no real AI CLI, no
network). A stub runner script emits a flag; a fake platform accepts it."""

import os
import stat
import sys
import tempfile
import unittest
import json
from unittest.mock import patch
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
                "max_agent_rounds": 2, "max_idle_rounds": 5, "model_timeout": 30, "legacy_unstructured_flags": True,
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

    def test_structured_candidates_exclude_incidental_flag(self):
        self.runner.write_text("""#!/usr/bin/env bash
echo '--- output begins ---'
echo 'example HTB{wrong}'
echo 'KOSHARY_RESULT: {"status":"candidate","evidence":["observed HTB{correct} in local output"],"artifacts":[],"candidates":["HTB{correct}"],"next_action":"submit"}'
""")
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        result = orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, db, platform, REPO, submit_mode="auto", auto_start=False)
        self.assertEqual(result["status"], "solved")
        self.assertEqual(platform.submitted, ["HTB{correct}"])
        self.assertTrue(list((self.root / "challenges").rglob("round_01.result.json")))

    def test_invalid_result_is_rejected(self):
        self.assertIsNone(orchestrator.parse_solver_result('KOSHARY_RESULT: {"status":"candidate"}'))
        self.assertIsNone(orchestrator.parse_solver_result('KOSHARY_RESULT: invalid'))

    def test_progress_and_repeated_evidence_control_idle(self):
        self.config["ctf"].update(max_agent_rounds=8, max_idle_rounds=2)
        observations = iter(["first test: 200", "second test: 403", "second test: 403", "second test: 403"])
        calls = []
        def run(*args, **kwargs):
            calls.append(1)
            item = {"status": "progress", "evidence": [next(observations)], "artifacts": [], "candidates": [], "next_action": "test"}
            return 0, "KOSHARY_RESULT: " + json.dumps(item)
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        with patch.object(orchestrator, "run_model", side_effect=run):
            orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, db, platform, REPO, submit_mode="none", auto_start=False)
        self.assertEqual(len(calls), 4)

    def test_execution_owner_controls_generated_actions(self):
        output = "RUN: printf test\n```python\nprint('test')\n```"
        for owner, expected in [("agent", 0), ("orchestrator", 1)]:
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as d:
                self.config["workspace"]["root"] = str(Path(d) / "challenges")
                self.config["models"]["gemini"]["execution_owner"] = owner
                self.config["ctf"]["max_agent_rounds"] = 1
                db = orchestrator.StateDB(Path(d) / "state.json")
                platform = FakePlatform()
                with patch.object(orchestrator, "run_model", return_value=(0, output)), \
                     patch.object(orchestrator, "run_model_commands", return_value=[]) as commands, \
                     patch.object(orchestrator, "run_generated_artifact", return_value=(0, "")) as artifact:
                    orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, db, platform, REPO, submit_mode="none", auto_start=False)
                    self.assertEqual(commands.call_count, expected)
                    self.assertEqual(artifact.call_count, expected)

    def test_invalid_execution_owner_skips(self):
        self.config["models"]["gemini"]["execution_owner"] = "invalid"
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        with patch.object(orchestrator, "run_model") as runner:
            result = orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, db, platform, REPO)
        self.assertEqual(result["status"], "skipped")
        runner.assert_not_called()

    def test_unverified_or_malformed_output_never_submits_by_default(self):
        self.config["ctf"].update(legacy_unstructured_flags=False, max_agent_rounds=1)
        samples = ["HTB{correct}", 'KOSHARY_RESULT: {bad json} HTB{correct}',
                   'KOSHARY_RESULT: {"status":"candidate","evidence":["a guess"],"artifacts":[],"candidates":["HTB{correct}"],"next_action":"submit"}']
        for output in samples:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as d:
                self.config["workspace"]["root"] = str(Path(d) / "challenges")
                platform = FakePlatform()
                with patch.object(orchestrator, "run_model", return_value=(0, output)):
                    orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, orchestrator.StateDB(Path(d) / "db.json"), platform, REPO, auto_start=False)
                self.assertEqual(platform.submitted, [])

    def test_failed_runner_does_not_submit_output(self):
        self.config["ctf"]["max_agent_rounds"] = 3
        platform = FakePlatform()
        with patch.object(orchestrator, "run_model", return_value=(1, "HTB{correct}")) as runner:
            orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, orchestrator.StateDB(self.root / "db.json"), platform, REPO, auto_start=False)
        self.assertEqual(platform.submitted, [])
        self.assertEqual(runner.call_count, 1)

    def test_fullpwn_template_contains_challenge_context(self):
        challenge = FakePlatform().get_challenge("misc-1")
        text = orchestrator.render_prompt(REPO / "prompts" / "fullpwn.md", challenge, self.root, 1, "inventory", "", env_info="test")
        self.assertIn("Challenge: Echo", text)
        self.assertIn("Description: d", text)
        self.assertIn("KOSHARY_RESULT:", text)

    def test_runner_receives_timeout(self):
        with patch.object(orchestrator, "run_subprocess", return_value=(0, "")) as run:
            orchestrator.run_model("bash /tmp/example.sh", self.root / "p.txt", self.root, timeout=42)
        self.assertEqual(run.call_args.kwargs["env"]["TIMEOUT_SECONDS"], "42")

    def test_optional_reference_is_not_inlined(self):
        ref = self.root / "references" / "ctf-misc"
        ref.mkdir(parents=True)
        (ref / "SKILL.md").write_text("long reference contents")
        self.config["ctf"].update(reference_root=str(ref.parent), max_agent_rounds=1)
        def run(runner, prompt_file, cwd, timeout):
            text = prompt_file.read_text()
            self.assertIn(str(ref / "SKILL.md"), text)
            self.assertNotIn("long reference contents", text)
            return 0, ""
        with patch.object(orchestrator, "run_model", side_effect=run):
            platform = FakePlatform()
            orchestrator.process_challenge(platform.get_challenge("misc-1"), self.config, orchestrator.StateDB(self.root / "db.json"), platform, REPO, auto_start=False)

    def test_duplicates_and_wrong_limit_stop_submissions(self):
        db = orchestrator.StateDB(self.root / "state" / "db.json")
        platform = FakePlatform()
        challenge = platform.get_challenge("misc-1")
        workspace = self.root / "challenge"
        workspace.mkdir()
        result = orchestrator._solve_with_candidates(challenge, ["HTB{wrong}", "HTB{wrong}", "HTB{other}"], platform, db, workspace, "auto", 1)
        self.assertFalse(result)
        self.assertEqual(platform.submitted, ["HTB{wrong}"])
        self.assertEqual(db.count_attempts(challenge.challenge_id), 1)

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
