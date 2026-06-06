import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import instance_manager as im  # noqa: E402
from platforms.base import NormalizedChallenge  # noqa: E402


class TestInstanceManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_target_and_instance(self):
        c = NormalizedChallenge("htb_ctf", "ev", "web-1", "n", "Web", 100, "",
                                target_kind="docker", host="1.2.3.4", port=80,
                                url="http://1.2.3.4:80")
        im.write_target(c, self.ws, started_by_koshary=True)
        im.write_instance("running", self.ws, raw={"x": 1})
        target = json.loads((self.ws / "target.json").read_text())
        inst = json.loads((self.ws / "instance.json").read_text())
        self.assertEqual(target["host"], "1.2.3.4")
        self.assertTrue(target["started_by_koshary"])
        self.assertEqual(inst["status"], "running")

    def test_tcp_reachable(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)  # OS completes the handshake from the backlog; no accept() needed
        port = srv.getsockname()[1]
        try:
            self.assertTrue(im.tcp_reachable("127.0.0.1", port, timeout=2))
        finally:
            srv.close()
        # A port nobody listens on should be unreachable.
        self.assertFalse(im.tcp_reachable("127.0.0.1", 1, timeout=1))

    def test_prepare_static_is_noop(self):
        class _P:
            def needs_instance(self, c):
                return c.target_kind in ("docker", "fullpwn")

        c = NormalizedChallenge("htb_ctf", "ev", "s-1", "n", "Crypto", 100, "", target_kind="static")
        out = im.prepare_target(_P(), c, self.ws, {"htb": {}})
        self.assertTrue((self.ws / "target.json").exists())
        self.assertEqual(out.target_kind, "static")


if __name__ == "__main__":
    unittest.main()
