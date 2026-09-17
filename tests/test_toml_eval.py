import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class TomlEvalSectionTest(unittest.TestCase):
    def _emit(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(text)
            path = handle.name
        return subprocess.run(
            [sys.executable, str(REPO / "lib/toml.py"), path],
            capture_output=True, text=True, check=True,
        ).stdout

    def test_single_test_command(self):
        out = self._emit('[eval]\ntest_command = "node --experimental-strip-types --test"\n')
        self.assertIn("TOML_EVAL_TEST_COMMAND='node --experimental-strip-types --test'", out)
        self.assertIn("TOML_EVAL_TEST_COMMANDS='node --experimental-strip-types --test'", out)

    def test_command_list_is_newline_separated(self):
        out = self._emit('[eval]\ntest_commands = ["pytest -q", "npm test --"]\n')
        self.assertIn("TOML_EVAL_TEST_COMMANDS='pytest -q\nnpm test --'", out)

    def test_absent_section_emits_nothing(self):
        self.assertNotIn("TOML_EVAL", self._emit('[project]\nname = "x"\n'))


if __name__ == "__main__":
    unittest.main()
