import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import logging_utils  # noqa: E402
from core.htb_cookie_client import (  # noqa: E402
    HTBAuthError,
    HTBCookieClient,
    parse_headers_file,
)
from core.logging_utils import StreamLogger, redact  # noqa: E402
from tests._fakehtb import AuthFailSession, FakeHTBSession  # noqa: E402

QUIET = StreamLogger("test", log_file=None, echo=False)


def make_client(session=None, **kw):
    return HTBCookieClient(
        ctf_id=1434, cookie="sess=COOKIEVALUE123", bearer="BEARERVALUE456",
        session=session or FakeHTBSession(), logger=QUIET, **kw,
    )


class TestHeadersParsing(unittest.TestCase):
    def test_parse_headers_file_extracts_only_needed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "htb_headers.txt"
            p.write_text(
                "GET /api/ctfs/1434 HTTP/2\n"
                "Host: ctf.hackthebox.com\n"
                "Cookie: sess=abc123\n"
                "Authorization: Bearer tok789\n"
                "User-Agent: Mozilla/5.0 Test\n"
                "Sec-Fetch-Mode: cors\n",
                encoding="utf-8",
            )
            headers = parse_headers_file(p)
        self.assertEqual(headers["cookie"], "sess=abc123")
        self.assertEqual(headers["authorization"], "Bearer tok789")
        self.assertEqual(headers["user-agent"], "Mozilla/5.0 Test")
        self.assertNotIn("sec-fetch-mode", headers)

    def test_missing_auth_raises(self):
        for key in ("HTB_CTF_COOKIE", "HTB_CTF_BEARER", "HTB_CTF_USER_AGENT"):
            os.environ.pop(key, None)
        with self.assertRaises(HTBAuthError):
            HTBCookieClient.from_env_or_headers_file(ctf_id=1434, logger=QUIET)


class TestAuthHeaders(unittest.TestCase):
    def test_cookie_bearer_sets_both(self):
        c = make_client()
        self.assertEqual(c.session.headers["Cookie"], "sess=COOKIEVALUE123")
        self.assertEqual(c.session.headers["Authorization"], "Bearer BEARERVALUE456")

    def test_bearer_only_mode_omits_cookie(self):
        c = make_client(auth_mode="bearer_only")
        self.assertNotIn("Cookie", c.session.headers)
        self.assertEqual(c.session.headers["Authorization"], "Bearer BEARERVALUE456")

    def test_bearer_prefix_is_stripped_once(self):
        c = HTBCookieClient(ctf_id=1434, bearer="Bearer abc", session=FakeHTBSession(), logger=QUIET)
        self.assertEqual(c.session.headers["Authorization"], "Bearer abc")

    def test_secrets_are_registered_for_redaction(self):
        make_client()
        masked = redact("leak sess=COOKIEVALUE123 and BEARERVALUE456 here")
        self.assertNotIn("COOKIEVALUE123", masked)
        self.assertNotIn("BEARERVALUE456", masked)
        self.assertIn("[REDACTED]", masked)


class TestReadEndpoints(unittest.TestCase):
    def setUp(self):
        self.c = make_client()

    def test_categories(self):
        cats = self.c.get_categories()
        self.assertEqual(cats[2], "Web")
        self.assertEqual(cats[4], "Crypto")

    def test_validate_access(self):
        can, menu = self.c.validate_access()
        self.assertTrue(can)
        self.assertEqual(menu["name"], "CTF Try Out")

    def test_list_challenges_raw(self):
        challs = self.c.list_challenges_raw()
        self.assertEqual(len(challs), 5)

    def test_get_challenge_raw(self):
        raw = self.c.get_challenge_raw(31856)
        self.assertEqual(raw["name"], "Dynastic")
        with self.assertRaises(KeyError):
            self.c.get_challenge_raw(999999)


class TestDownloadLink(unittest.TestCase):
    def test_download_link(self):
        c = make_client()
        url = c.get_download_link(31856)
        self.assertTrue(url.startswith("https://ctf.hackthebox.com/challenges/31856/download"))

    def test_fetch_writes_file(self):
        c = make_client()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "dynastic.zip"
            c.fetch(c.get_download_link(31856), out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)


class TestContainers(unittest.TestCase):
    def test_start_and_stop(self):
        sess = FakeHTBSession()
        c = make_client(session=sess)
        self.assertIn("message", c.start_container(40001))
        self.assertEqual(sess.start_count, 1)
        self.assertIn("message", c.stop_container(40001))
        self.assertEqual(sess.stop_count, 1)

    def test_poll_until_ready_returns_online_challenge(self):
        c = make_client()
        raw = c.poll_until_ready(40001, poll_seconds=5, interval=0.0)
        self.assertEqual(raw["hostname"], "94.237.10.10")
        self.assertEqual(raw["docker_ports"], [30001])


class TestSubmission(unittest.TestCase):
    def setUp(self):
        self.c = make_client()

    def test_wrong_flag_is_not_accepted(self):
        res = self.c.submit_flag(31856, "HTB{nope}")
        self.assertFalse(res["accepted"])
        self.assertEqual(res["status_code"], 400)
        self.assertIn("Wrong", res["message"])

    def test_correct_flag_is_accepted(self):
        res = self.c.submit_flag(31856, "HTB{correct}")
        self.assertTrue(res["accepted"])
        self.assertEqual(res["status_code"], 200)


class TestAuthErrors(unittest.TestCase):
    def test_401_raises_auth_error(self):
        c = make_client(session=AuthFailSession())
        with self.assertRaises(HTBAuthError):
            c.get_event()


if __name__ == "__main__":
    unittest.main()
