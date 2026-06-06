import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.downloads import extract_archive, prepare_files, sha256_file  # noqa: E402


class TestDownloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_zip(self, path: Path):
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("hello.txt", "the flag is HTB{zip}")

    def test_sha256(self):
        f = self.root / "a.bin"
        f.write_bytes(b"abc")
        self.assertEqual(len(sha256_file(f)), 64)

    def test_extract_zip(self):
        archive = self.root / "src.zip"
        self._make_zip(archive)
        dest = self.root / "out"
        self.assertTrue(extract_archive(archive, dest))
        self.assertTrue((dest / "hello.txt").exists())

    def test_prepare_files_local_with_extraction(self):
        archive = self.root / "src.zip"
        self._make_zip(archive)
        files_dir = self.root / "ws" / "files"
        meta = prepare_files([{"path": str(archive)}], files_dir, password="hackthebox")
        self.assertEqual(len(meta), 1)
        self.assertTrue(meta[0]["extracted"])
        self.assertEqual(meta[0]["filename"], "src.zip")
        # Extracted content lands under ws/extracted/src.zip/
        self.assertTrue((self.root / "ws" / "extracted" / "src.zip" / "hello.txt").exists())
        self.assertTrue((files_dir / "files_metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
