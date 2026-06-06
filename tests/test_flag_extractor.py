import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.flag_extractor import (  # noqa: E402
    HTB_DEFAULT_PATTERNS,
    extract_candidate_answers,
    extract_flags,
    is_placeholder_flag,
)


class TestFlagExtractor(unittest.TestCase):
    def test_htb_and_chtb(self):
        text = "found HTB{abc_def} then CHTB{xyz-1}"
        flags = extract_flags(text, HTB_DEFAULT_PATTERNS)
        self.assertIn("HTB{abc_def}", flags)
        self.assertIn("CHTB{xyz-1}", flags)
        # The HTB pattern must not produce a spurious HTB{xyz-1} from CHTB{...}.
        self.assertNotIn("HTB{xyz-1}", flags)

    def test_dedup_preserves_order(self):
        text = "HTB{a} HTB{b} HTB{a}"
        self.assertEqual(extract_flags(text, HTB_DEFAULT_PATTERNS), ["HTB{a}", "HTB{b}"])

    def test_bad_pattern_is_skipped(self):
        # An invalid regex must not raise.
        self.assertEqual(extract_flags("HTB{a}", ["(", *HTB_DEFAULT_PATTERNS]), ["HTB{a}"])

    def test_placeholder_flags_are_dropped(self):
        # The literal example from the prompt must never become a candidate.
        text = "The flag format is HTB{...}. The real flag is HTB{r3al_one}."
        flags = extract_flags(text, HTB_DEFAULT_PATTERNS)
        self.assertEqual(flags, ["HTB{r3al_one}"])
        self.assertTrue(is_placeholder_flag("HTB{...}"))
        self.assertTrue(is_placeholder_flag("flag{FLAG_HERE}"))
        self.assertFalse(is_placeholder_flag("HTB{r3al_one}"))

    def test_candidate_answers(self):
        text = (
            "blah\nFINAL_ANSWER_CANDIDATE: CVE-2024-1234\n"
            "CONFIDENCE: high\nEVIDENCE: banner says so\n"
        )
        cands = extract_candidate_answers(text)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].value, "CVE-2024-1234")
        self.assertEqual(cands[0].confidence, "high")


if __name__ == "__main__":
    unittest.main()
