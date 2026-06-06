import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platforms.base import NormalizedChallenge, SubmitResult  # noqa: E402


class TestNormalizedChallenge(unittest.TestCase):
    def test_slug(self):
        c = NormalizedChallenge("htb_ctf", "ev", "1", "Hello World!", "Web", 100, "")
        self.assertEqual(c.slug, "hello-world")

    def test_connection_info_prefers_url(self):
        c = NormalizedChallenge("htb_ctf", "ev", "1", "n", "Web", 100, "",
                                url="http://h:1", host="h", port=1)
        self.assertEqual(c.connection_info, "http://h:1")

    def test_connection_info_host_port(self):
        c = NormalizedChallenge("htb_ctf", "ev", "1", "n", "Pwn", 100, "", host="h", port=1337)
        self.assertEqual(c.connection_info, "h:1337")

    def test_connection_info_none(self):
        c = NormalizedChallenge("ctfd", "ev", "1", "n", "Misc", 100, "")
        self.assertIsNone(c.connection_info)

    def test_submit_result_defaults(self):
        r = SubmitResult(accepted=True, message="ok")
        self.assertTrue(r.accepted)
        self.assertFalse(r.already_solved)
        self.assertEqual(r.raw, {})


if __name__ == "__main__":
    unittest.main()
