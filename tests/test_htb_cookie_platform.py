import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.htb_cookie_client import HTBCookieClient  # noqa: E402
from core.logging_utils import StreamLogger  # noqa: E402
from platforms.htb_cookie import HTBCookiePlatform  # noqa: E402
from tests._fakehtb import FakeHTBSession  # noqa: E402

QUIET = StreamLogger("test", log_file=None, echo=False)

CONFIG = {"htb_cookie": {"ctf_id": 1434, "download_password": "hackthebox",
                         "poll_seconds": 5, "poll_interval": 0}}


def make_platform(session=None):
    client = HTBCookieClient(
        ctf_id=1434, cookie="c", bearer="b",
        session=session or FakeHTBSession(), logger=QUIET,
    )
    return HTBCookiePlatform(CONFIG, logger=QUIET, client=client)


class TestNormalization(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()
        self.by_id = {c.challenge_id: c for c in self.p.list_challenges()}

    def test_counts(self):
        self.assertEqual(len(self.by_id), 5)

    def test_static_challenge(self):
        c = self.by_id["31856"]
        self.assertEqual(c.category, "Crypto")
        self.assertEqual(c.target_kind, "static")
        self.assertEqual(c.points, 300)
        self.assertEqual(c.files, ["dynastic.zip"])
        self.assertFalse(c.vpn_required)

    def test_docker_web_gets_url(self):
        c = self.by_id["40001"]
        self.assertEqual(c.target_kind, "docker")
        self.assertEqual(c.host, "94.237.10.10")
        self.assertEqual(c.port, 30001)
        self.assertEqual(c.url, "http://94.237.10.10:30001")

    def test_docker_tcp_has_no_url(self):
        c = self.by_id["40002"]
        self.assertEqual(c.target_kind, "docker")
        self.assertEqual(c.host, "94.237.10.20")
        self.assertEqual(c.port, 30002)
        self.assertIsNone(c.url)

    def test_fullpwn(self):
        c = self.by_id["50001"]
        self.assertEqual(c.target_kind, "fullpwn")
        self.assertTrue(c.vpn_required)

    def test_solved_carried_through(self):
        self.assertTrue(self.by_id["60001"].solved)


class TestInstanceLifecycle(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()
        self.by_id = {c.challenge_id: c for c in self.p.list_challenges()}

    def test_needs_instance(self):
        self.assertTrue(self.p.needs_instance(self.by_id["40001"]))   # docker
        self.assertTrue(self.p.needs_instance(self.by_id["40002"]))   # docker tcp
        self.assertFalse(self.p.needs_instance(self.by_id["31856"]))  # static
        # Fullpwn is gated off by default (auto_start_fullpwn=False).
        self.assertFalse(self.p.needs_instance(self.by_id["50001"]))

    def test_start_instance_sets_target(self):
        started = self.p.start_instance(self.by_id["40001"])
        self.assertEqual(started.host, "94.237.10.10")
        self.assertEqual(started.port, 30001)
        self.assertEqual(started.url, "http://94.237.10.10:30001")

    def test_stop_instance(self):
        sess = FakeHTBSession()
        p = make_platform(session=sess)
        chall = {c.challenge_id: c for c in p.list_challenges()}["40001"]
        p.stop_instance(chall)
        self.assertEqual(sess.stop_count, 1)

    def test_instance_status(self):
        status = self.p.instance_status(self.by_id["40001"])
        self.assertEqual(status["status"], "running")
        self.assertTrue(status["docker_online"])


class TestDownload(unittest.TestCase):
    def test_download_writes_files(self):
        p = make_platform()
        chall = {c.challenge_id: c for c in p.list_challenges()}["31856"]
        with tempfile.TemporaryDirectory() as d:
            written = p.download_files(chall, d)
            self.assertEqual(len(written), 1)
            self.assertTrue(Path(written[0]).exists())
            self.assertTrue((Path(d) / "files_metadata.json").exists())

    def test_no_download_for_fileless_challenge(self):
        p = make_platform()
        chall = {c.challenge_id: c for c in p.list_challenges()}["50001"]
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(p.download_files(chall, d), [])


class TestSubmission(unittest.TestCase):
    def setUp(self):
        self.p = make_platform()
        self.chall = {c.challenge_id: c for c in self.p.list_challenges()}["31856"]

    def test_correct(self):
        res = self.p.submit_flag(self.chall, "HTB{correct}")
        self.assertTrue(res.accepted)

    def test_wrong(self):
        res = self.p.submit_flag(self.chall, "HTB{nope}")
        self.assertFalse(res.accepted)
        self.assertIn("Wrong", res.message)


class TestScoreboard(unittest.TestCase):
    def test_scoreboard(self):
        board = make_platform().get_scoreboard()
        self.assertEqual(board[0]["team"], "alpha")


if __name__ == "__main__":
    unittest.main()
