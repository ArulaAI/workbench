import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib.eval_execution import load_config


class TomlEvalSectionTest(unittest.TestCase):
    def _commands(self, text: str, fallback=False) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "speed.toml").write_text(text)
            with patch.dict("os.environ", {}, clear=True):
                if fallback:
                    with patch.dict(sys.modules, {"tomllib": None, "tomli": None}):
                        return load_config(root)["test_commands"]
                return load_config(root)["test_commands"]

    def test_single_test_command(self):
        self.assertEqual(["node --experimental-strip-types --test"], self._commands(
            '[eval]\ntest_command = "node --experimental-strip-types --test"\n'))

    def test_command_list_preserves_commands(self):
        self.assertEqual(["pytest -q", "npm test --"], self._commands(
            '[eval]\ntest_commands = ["pytest -q", "npm test --"]\n'))

    def test_absent_section_has_no_commands(self):
        self.assertEqual([], self._commands('[project]\nname = "x"\n'))

    def test_fallback_comments_cannot_truncate_or_invent_array_commands(self):
        for text in (
            '[eval]\ntest_commands = ["pytest -q", # interior comment\n"npm test --"]\n',
            '[eval]\ntest_commands = [ # ] in opening comment\n"pytest -q",\n'
            '# a whole comment ]\n"npm test --", # ] in item comment\n] # trailing ]\n',
            '[eval]\ntest_commands = ["pytest -q", "npm test --"] # trailing ]\n',
        ):
            with self.subTest(text=text):
                self.assertEqual(["pytest -q", "npm test --"], self._commands(text, fallback=True))

    def test_fallback_preserves_hashes_and_brackets_inside_strings(self):
        text = '''[eval]
test_commands = [
    'echo "# [literal]"', # ignored ]
    "echo [brackets] # string",
]
'''
        self.assertEqual(['echo "# [literal]"', "echo [brackets] # string"],
                         self._commands(text, fallback=True))

    def test_fallback_preserves_escaped_quotes_around_hash(self):
        text = r'''[eval]
test_commands = ["echo \"# inside\"", "pytest -q"] # ]
'''
        self.assertEqual(['echo "# inside"', "pytest -q"], self._commands(text, fallback=True))


if __name__ == "__main__":
    unittest.main()
