import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platforms.ctfd import CTFdPlatform  # noqa: E402

CONFIG = {"ctf": {"name": "DemoCTF", "base_url": "https://demo.ctf"}}


class FakeCTFd:
    def get_challenges(self):
        return [
            {"id": 1, "name": "Sanity", "category": "Misc", "value": 50, "solved_by_me": False},
            {"id": 2, "name": "Web One", "category": "Web", "value": 100, "solved_by_me": True},
        ]

    def get_challenge_detail(self, cid):
        return {
            "id": cid, "name": "Sanity", "category": "Misc", "value": 50,
            "description": "welcome", "files": ["/files/a.txt"], "solved_by_me": False,
        }

    def submit_flag(self, cid, flag):
        if flag == "flag{good}":
            return {"success": True, "data": {"status": "correct", "message": "Correct"}}
        return {"success": True, "data": {"status": "incorrect", "message": "Incorrect"}}


class TestCTFdAdapter(unittest.TestCase):
    def setUp(self):
        self.p = CTFdPlatform(CONFIG, client=FakeCTFd())

    def test_list_challenges(self):
        challs = self.p.list_challenges()
        self.assertEqual(len(challs), 2)
        self.assertEqual(challs[0].platform, "ctfd")
        self.assertEqual(challs[0].challenge_id, "1")
        self.assertTrue(challs[1].solved)

    def test_get_challenge_detail(self):
        c = self.p.get_challenge("1")
        self.assertEqual(c.points, 50)
        self.assertEqual(c.files, ["/files/a.txt"])
        self.assertEqual(c.target_kind, "static")

    def test_submit_correct_and_wrong(self):
        c = self.p.get_challenge("1")
        self.assertTrue(self.p.submit_flag(c, "flag{good}").accepted)
        self.assertFalse(self.p.submit_flag(c, "flag{bad}").accepted)


if __name__ == "__main__":
    unittest.main()
