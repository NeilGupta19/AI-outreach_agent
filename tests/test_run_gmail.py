import subprocess
import sys
import unittest


class RunGmailTests(unittest.TestCase):
    def test_missing_credentials_prints_setup_help(self):
        result = subprocess.run(
            [
                sys.executable,
                "run_gmail.py",
                "--credentials",
                "missing-credentials.json",
                "--token",
                "missing-token.json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("OAuth client file not found: missing-credentials.json", result.stderr)
        self.assertIn("Google Cloud OAuth Desktop app client", result.stderr)
        self.assertIn("python3 run_demo.py", result.stderr)


if __name__ == "__main__":
    unittest.main()
