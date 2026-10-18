import unittest
from sync_github_sources import zip_member_destination

class SourceSyncTests(unittest.TestCase):
    def test_safe_asset(self):
        self.assertEqual(str(zip_member_destination("repo-main/assets/icon.png", "repo")), "assets/icon.png")
    def test_no_escape(self):
        self.assertIsNone(zip_member_destination("repo-main/../../outside.py", "repo"))
        self.assertIsNone(zip_member_destination("/etc/passwd", "repo"))
    def test_excludes_binaries_and_captures(self):
        self.assertIsNone(zip_member_destination("repo-main/bin/app.exe", "repo"))
        self.assertIsNone(zip_member_destination("repo-main/fixtures/game.pcapng", "repo"))

if __name__ == "__main__":
    unittest.main()
