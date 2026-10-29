"""Run the demo's tests with the standard library only (no pytest needed).

    python3 run_tests.py                                  every test
    python3 run_tests.py tests/test_app.py::AddTest::test_add   one test

speed eval sets SPEED_EVAL_RESULT_FILE; each selected test's result is written there.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load(selector):
    path, _, rest = selector.partition("::")
    name = ".".join([path[:-3].replace("/", "."), *filter(None, rest.split("::"))])
    return unittest.defaultTestLoader.loadTestsFromName(name)


class Recorder(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append((test, "pass"))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append((test, "fail"))

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append((test, "error"))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append((test, "skipped"))


def main(selectors):
    suite = unittest.TestSuite(load(s) for s in selectors) if selectors else \
        unittest.defaultTestLoader.discover("tests", top_level_dir=".")
    result = unittest.TextTestRunner(resultclass=Recorder, verbosity=2).run(suite)
    report = os.environ.get("SPEED_EVAL_RESULT_FILE")
    if report:
        tests = [{"id": test.id(), "status": status} for test, status in result.records]
        with open(report, "w", encoding="utf-8") as handle:
            json.dump({"tests": tests}, handle)
    return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
