import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platforms.htb_ctf_mcp import HTBCTFPlatform  # noqa: E402
from tests._fakemcp import FakeMCP  # noqa: E402

CONFIG = {"htb": {"event": "cyber-apocalypse-2026", "download_password": "hackthebox", "tools": {}}}


def make_platform():
    return HTBCTFPlatform(CONFIG, client=FakeMCP())


class TestToolResolution(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()

    def test_roles_resolve_to_expected_tools(self):
        self.assertEqual(self.p._resolve("list_events"), "list_ctf_events")
        self.assertEqual(self.p._resolve("get_event"), "get_ctf_event")
        self.assertEqual(self.p._resolve("list_challenges"), "list_challenges")
        self.assertEqual(self.p._resolve("get_challenge"), "get_challenge")
        self.assertEqual(self.p._resolve("start_instance"), "spawn_docker_instance")
        self.assertEqual(self.p._resolve("stop_instance"), "stop_docker_instance")
        self.assertEqual(self.p._resolve("instance_status"), "get_instance_status")
        self.assertEqual(self.p._resolve("submit_flag"), "submit_flag")
        self.assertEqual(self.p._resolve("scoreboard"), "get_scoreboard")

    def test_arg_mapping_uses_schema_names(self):
        args = self.p._build_args("submit_flag", {"event": "E", "challenge": "C", "flag": "F"})
        self.assertEqual(args, {"event_id": "E", "challenge_id": "C", "flag": "F"})

    def test_override_takes_precedence(self):
        cfg = {"htb": {"event": "e", "tools": {"submit_flag": "get_scoreboard"}}}
        p = HTBCTFPlatform(cfg, client=FakeMCP())
        self.assertEqual(p._resolve("submit_flag"), "get_scoreboard")


class TestNormalization(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()

    def test_list_events(self):
        events = self.p.list_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["slug"], "cyber-apocalypse-2026")

    def test_list_challenges_normalization(self):
        challs = self.p.list_challenges()
        by_id = {c.challenge_id: c for c in challs}
        self.assertEqual(by_id["web-123"].target_kind, "docker")
        self.assertEqual(by_id["web-123"].points, 325)
        self.assertEqual(len(by_id["web-123"].files), 1)
        # Fullpwn challenge must be flagged vpn_required.
        self.assertEqual(by_id["fp-1"].target_kind, "fullpwn")
        self.assertTrue(by_id["fp-1"].vpn_required)
        # Solved flag is carried through.
        self.assertTrue(by_id["crypto-9"].solved)

    def test_get_challenge(self):
        c = self.p.get_challenge("web-123")
        self.assertEqual(c.name, "Example Web")
        self.assertEqual(c.target_kind, "docker")

    def test_start_instance_sets_target(self):
        challs = {c.challenge_id: c for c in self.p.list_challenges()}
        pwn = challs["pwn-7"]
        started = self.p.start_instance(pwn)
        self.assertEqual(started.host, "94.237.10.20")
        self.assertEqual(started.port, 31337)
        # URL is synthesized when only host:port are returned.
        self.assertEqual(started.url, "http://94.237.10.20:31337")


class TestSubmission(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()
        self.chall = self.p.list_challenges()[0]

    def test_correct_flag(self):
        res = self.p.submit_flag(self.chall, "HTB{correct}")
        self.assertTrue(res.accepted)

    def test_wrong_flag(self):
        res = self.p.submit_flag(self.chall, "HTB{nope}")
        self.assertFalse(res.accepted)

    def test_scoreboard(self):
        board = self.p.get_scoreboard()
        self.assertEqual(board[0]["team"], "alpha")


if __name__ == "__main__":
    unittest.main()
