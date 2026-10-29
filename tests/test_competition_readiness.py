import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from orchestrator import category_prompt, collect_history_text, collect_workspace_text, collect_workspace_inventory, run_subprocess, choose_route


class CompetitionReadinessTests(unittest.TestCase):
    def test_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_subprocess([sys.executable, "-c", "import time; time.sleep(10)"], Path(d), timeout=0.05)

    def test_routing_prefers_specific_alias(self):
        self.assertEqual(choose_route("web exploitation", {"web": "codex", "web exploitation": "claude"}), "claude")

    def test_category_independent_of_runner(self):
        for category, expected in [('Web Exploitation', 'web'), ('Binary Exploitation', 'pwn'), ('Reverse Engineering', 'rev'), ('Cryptography', 'crypto'), ('DFIR', 'forensics'), ('Android', 'mobile'), ('Hardware', 'hardware'), ('Blockchain', 'blockchain')]:
            with self.subTest(category=category):
                self.assertEqual(category_prompt(category, 'custom'), f'prompts/{expected}.txt')
        self.assertEqual(category_prompt('unknown', 'custom'), 'custom')

    def test_workspace_limits(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'a.txt').write_text('abcdefgh')
            (p / 'b.txt').write_text('other')
            result = collect_workspace_text(p, max_files=1, max_chars_per_file=3)
            self.assertIn('abc', result)
            self.assertNotIn('def', result)
            self.assertNotIn('b.txt', result)

    def test_inventory_includes_binary_without_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "binary").write_bytes(b"secret-content")
            (p / "agent_rounds").mkdir()
            (p / "agent_rounds" / "log.txt").write_text("log")
            result = collect_workspace_inventory(p)
            self.assertIn("binary (14 bytes)", result)
            self.assertNotIn("secret-content", result)
            self.assertNotIn("log.txt", result)

    def test_structured_history_uses_evidence_not_verbose_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agent_rounds"
            p.mkdir()
            record = {"status": "progress", "evidence": ["observed 403"], "artifacts": [], "candidates": [], "next_action": "inspect"}
            (p / "round_01.result.json").write_text(json.dumps(record))
            (p / "round_01.out.txt").write_text("verbose output")
            result = collect_history_text(Path(d), 2)
            self.assertIn("observed 403", result)
            self.assertNotIn("verbose output", result)

    def test_history_uses_most_recent_rounds(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'agent_rounds'
            p.mkdir()
            for i in range(1, 6):
                (p / f'round_{i:02d}.out.txt').write_text(f'output {i}')
            result = collect_history_text(Path(d), 6)
            self.assertNotIn('output 1', result)
            self.assertIn('output 5', result)
