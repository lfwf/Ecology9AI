"""Regression cases for bounded inspection of offline analyzer results."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'oa-workflow-expert/skills/oa-workflow-analysis/scripts/inspect_workflow.py'


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = {
            'source': {'sha256': 'a' * 64},
            'analyzer': {'runtime_verified': False},
            'summary': {'node_count': 2},
            'workflows': [{
                'id': 'demo', 'name': '合成测试流程',
                'nodes': [{'id': '1', 'name': '创建'}, {'id': '2', 'name': '审核'}],
                'links': [{'id': '10', 'from_node': '1', 'to_node': '2', 'condition': '', 'source_refs': ['ev1']}],
                'fields': [], 'operator_groups': [], 'formulas': [], 'permissions': []
            }],
            'scripts': [
                {'id': 'script1', 'workflow_id': 'demo', 'node_id': '1', 'active': True, 'text': '甲\n乙\n丙\n丁', 'source_refs': []},
                {'id': 'script2', 'workflow_id': 'demo', 'node_id': '1', 'active': False, 'text': '停用代码', 'source_refs': []},
            ],
            'gaps': [{'category': 'runtime', 'code': 'RUNTIME_VERSION'}],
        }
        self.evidence = [
            {'id': 'ev1', 'table': 'workflow_nodelink', 'line': 4, 'values': {}},
            {'id': 'ev2', 'table': 'rule_maplist', 'line': 10, 'values': {'ruleid': '70', 'linkid': '10', 'rulesrc': '1', 'isused': '1', 'wfid': 'demo'}},
            {'id': 'ev3', 'table': 'rule_base', 'line': 11, 'values': {'id': '70', 'linkid': '10', 'rulesrc': '1', 'condit': '金额大于5000'}},
        ]
        self.write()

    def write(self):
        (self.root / 'agent-context.json').write_text(json.dumps(self.context, ensure_ascii=False), 'utf-8')
        (self.root / 'evidence.json').write_text(json.dumps({'records': self.evidence}, ensure_ascii=False), 'utf-8')

    def run_cli(self, *args):
        self.assertTrue(SCRIPT.is_file(), 'Missing bounded workflow inspector')
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root), *args], capture_output=True, text=True, encoding='utf-8')

    def read_cli(self, *args):
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_empty_link_condition_still_recovers_separate_rule_with_evidence(self):
        result = self.read_cli('--section', 'routes')
        route = result['items'][0]
        self.assertEqual(route['linked_rules'][0]['condition'], '金额大于5000')
        self.assertEqual(route['linked_rules'][0]['source_refs'], ['ev2', 'ev3'])
        self.assertEqual(route['rule_combination'], 'not_verified')
        self.assertFalse(result['runtime_verified'])

    def test_script_requires_explicit_slice_and_preserves_line_numbers(self):
        listing = self.read_cli('--section', 'scripts')
        self.assertNotIn('text', listing['items'][0])
        sliced = self.read_cli('--section', 'scripts', '--script', 'script1', '--start', '2', '--limit', '2')
        self.assertEqual(sliced['items'][0]['lines'], [{'line': 2, 'text': '乙'}, {'line': 3, 'text': '丙'}])
        self.assertTrue(sliced['items'][0]['truncated'])

    def test_inactive_script_remains_visible_as_inactive(self):
        result = self.read_cli('--section', 'scripts')
        self.assertFalse(result['items'][1]['active'])

    def test_pagination_and_missing_workflow_are_explicit(self):
        result = self.read_cli('--section', 'nodes', '--offset', '1', '--limit', '1')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['items'][0]['id'], '2')
        missing = self.run_cli('--workflow', 'unknown')
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('WORKFLOW_NOT_FOUND', missing.stdout)

    def test_large_evidence_is_bounded_and_does_not_execute_export_text(self):
        self.evidence[0]['values']['script'] = 'untrusted ' * 10000
        self.write()
        result = self.read_cli('--section', 'evidence', '--ref', 'ev1')
        value = result['items'][0]['values']['script']
        self.assertTrue(value['truncated'])
        self.assertEqual(len(value['sha256_utf8']), 64)
        self.assertLess(len(json.dumps(result)), 6000)

    def test_unknown_reference_fails_instead_of_silently_returning_empty(self):
        result = self.run_cli('--section', 'evidence', '--ref', 'nonexistent')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('EVIDENCE_NOT_FOUND', result.stdout)

    def test_page_respects_output_budget_without_hiding_remaining_items(self):
        self.context['workflows'][0]['nodes'] = [{'id': str(i), 'name': '测试名称' * 300} for i in range(30)]
        self.write()
        result = self.run_cli('--section', 'nodes', '--limit', '30', '--max-output-chars', '8000')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLessEqual(len(result.stdout), 8000)
        output = json.loads(result.stdout)
        self.assertTrue(output['has_more'])
        self.assertEqual(output['next_offset'], len(output['items']))

    def test_gap_filters_match_exact_workflow_and_node_tokens(self):
        self.context['workflows'].append({'id': 'other', 'name': '其他流程', 'nodes': [], 'links': []})
        self.context['gaps'] = [
            {'id': 'g1', 'scope': 'workflow:demo/node:1', 'category': 'runtime'},
            {'id': 'g2', 'scope': 'workflow:demo/node:10', 'category': 'runtime'},
            {'id': 'g3', 'scope': 'workflow:other/node:1', 'category': 'runtime'},
            {'id': 'g4', 'scope': 'table:rule_base', 'category': 'unsupported'},
        ]
        self.write()
        output = self.read_cli('--section', 'gaps', '--workflow', 'demo', '--node', '1')
        self.assertEqual([g['id'] for g in output['items']], ['g1'])

    def test_script_with_missing_workflow_id_uses_node_membership(self):
        self.context['scripts'][0]['workflow_id'] = ''
        self.write()
        output = self.read_cli('--section', 'scripts', '--workflow', 'demo', '--script', 'script1')
        script = output['items'][0]
        self.assertEqual(script['candidate_workflow_ids'], ['demo'])
        self.assertEqual(script['ownership'], 'inferred_from_node_or_layout')

    def test_ambiguous_script_ownership_is_reported_not_silently_assigned(self):
        self.context['scripts'][0]['workflow_id'] = ''
        self.context['workflows'].append({'id': 'other', 'name': '其他流程', 'nodes': [{'id': '1', 'name': '共享节点'}], 'links': []})
        self.write()
        output = self.read_cli('--section', 'scripts', '--script', 'script1')
        script = output['items'][0]
        self.assertEqual(script['ownership'], 'ambiguous')
        self.assertEqual(set(script['candidate_workflow_ids']), {'demo', 'other'})


if __name__ == '__main__':
    unittest.main()
