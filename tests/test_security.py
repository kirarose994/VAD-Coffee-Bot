import re
import subprocess
import unittest
from pathlib import Path


class RepositorySecurityTests(unittest.TestCase):
    def test_no_token_or_private_key_is_committed(self):
        root = Path(__file__).parents[1]
        tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
        telegram_token = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
        private_key = "-----BEGIN " + "PRIVATE KEY-----"
        offenders = []
        for relative in tracked:
            path = root / relative
            if not path.is_file():
                continue
            try: text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError: continue
            if telegram_token.search(text) or private_key in text:
                offenders.append(relative)
        self.assertEqual(offenders, [], f"Possible committed secrets in: {offenders}")


if __name__ == "__main__": unittest.main()
