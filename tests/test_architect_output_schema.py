"""The Architect must produce the provenance consumed by the planning gates."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'templates/architect-output.json').read_text())

class ArchitectReferences(unittest.TestCase):
    def setUp(self):
        self.validator = Draft202012Validator(SCHEMA['properties']['tasks'])
        self.task = {'id': '1', 'title': 'Fix fee', 'description': 'Round fees half up',
                     'acceptance_criteria': 'RISK-02 passes', 'depends_on': [],
                     'agent_model': 'sonnet', 'files_touched': ['src/payments/service.ts']}

    def reference(self, spec):
        return {'spec': spec, 'section': 'Expected Behavior', 'requirement': 'Resolve the documented defect'}

    def test_missing_reference_is_rejected(self):
        self.assertTrue(list(self.validator.iter_errors([self.task])))

    def test_empty_references_are_rejected(self):
        self.task['spec_references'] = []
        self.assertTrue(list(self.validator.iter_errors([self.task])))

    def test_incomplete_reference_is_rejected(self):
        self.task['spec_references'] = [{'spec': 'specs/defects/fee.md'}]
        self.assertTrue(list(self.validator.iter_errors([self.task])))

    def test_two_tasks_with_distinct_defect_references_are_accepted(self):
        self.task['spec_references'] = [self.reference('specs/defects/fee.md')]
        second = copy.deepcopy(self.task)
        second.update(id='2', title='Test retries', files_touched=['test/refund-retry.test.ts'],
                      spec_references=[self.reference('specs/defects/retry.md')])
        self.validator.validate([self.task, second])

if __name__ == '__main__':
    unittest.main()
