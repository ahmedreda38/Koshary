import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clean_workspace as cw  # noqa: E402


class TestCleanWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = self.root / ".env"
        self.env.write_text("CTFD_SESSION=sess123\nHTB_MCP_TOKEN=tok456\nKEEP=me\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scrub_both_secrets_keep_key(self):
        cw.scrub_env(self.env)
        text = self.env.read_text()
        self.assertIn("CTFD_SESSION=", text)
        self.assertIn("HTB_MCP_TOKEN=", text)
        self.assertNotIn("sess123", text)
        self.assertNotIn("tok456", text)
        self.assertIn("KEEP=me", text)

    def test_keep_htb_token(self):
        cw.scrub_env(self.env, keep_htb_token=True)
        text = self.env.read_text()
        self.assertIn("HTB_MCP_TOKEN=tok456", text)
        self.assertNotIn("sess123", text)

    def test_scrub_config_scrubs_htb_event(self):
        import json

        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({
            "ctf": {"name": "x", "base_url": "u", "flag_patterns": ["a"]},
            "htb": {"event": "cyber-apocalypse-2026", "mcp_url": "https://x"},
            "routing": {"web": "codex"},
        }), encoding="utf-8")
        cw.scrub_config(cfg)
        data = json.loads(cfg.read_text())
        self.assertEqual(data["htb"]["event"], "")
        self.assertEqual(data["htb"]["mcp_url"], "https://x")  # connection settings kept
        self.assertEqual(data["routing"], {"web": "codex"})    # routing kept


if __name__ == "__main__":
    unittest.main()
