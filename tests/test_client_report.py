import json
import unittest
from src.codex_sessions import parse_session_lines
from src.codex_activity import build_activity
from src.generate_report import generate_report
from src.metrics import build_metrics
from tests.test_generate_report import make_data, CODEX_AVAILABLE


def parsed(records, owner='s1'):
    lines = [json.dumps({'type': 'session_meta', 'timestamp': '2026-09-01T00:00:00Z',
                         'payload': {'id': owner, 'cwd': '/project'}})]
    for response, stamp, usage in records:
        lines.append(json.dumps({'type': 'token_usage_record', 'timestamp': stamp,
                                'payload': {'thread_id': owner, 'response_id': response,
                                            'usage': usage}}))
    return parse_session_lines(lines)


def counts(n=100):
    return {'input_tokens': n, 'cached_input_tokens': 80,
            'output_tokens': 20, 'reasoning_output_tokens': 5, 'total_tokens': n+20}


def aggregate(sessions):
    return build_activity(sessions, period={'start': '2026-09-01', 'end': '2026-09-17'},
                          timezone_name='UTC', coverage={'files_parsed': len(sessions)})


class TestClientReport(unittest.TestCase):
    def test_token_records_deduplicate_and_filter_period_without_adding_subsets(self):
        records = [('r1', '2026-09-07T12:00:00Z', counts()),
                   ('r1', '2026-09-07T12:00:00Z', counts()),
                   ('old', '2026-08-31T12:00:00Z', counts()),
                   ('r2', '2026-09-08T12:00:00Z', counts(200))]
        result = aggregate([parsed(records), parsed(records)])['tokens']
        self.assertEqual(result['total_tokens'], 340)
        self.assertEqual(result['cached_input_tokens'], 160)
        self.assertEqual(result['reasoning_output_tokens'], 10)
        self.assertEqual(result['responses'], 2)
        self.assertEqual(result['first_event'], '2026-09-07T12:00:00+00:00')
        self.assertTrue(result['partial'])

    def test_foreign_thread_usage_is_not_attributed_to_a_fork(self):
        lines = [json.dumps({'type': 'session_meta', 'timestamp': '2026-09-01T00:00:00Z',
                            'payload': {'id': 'child', 'cwd': '/project'}}),
                 json.dumps({'type': 'token_usage_record', 'timestamp': '2026-09-07T00:00:00Z',
                             'payload': {'thread_id': 'parent', 'response_id': 'r',
                                         'usage': counts()}})]
        result = aggregate([parse_session_lines(lines)])['tokens']
        self.assertFalse(result['available'])

    def test_token_period_uses_travel_timezone(self):
        session = parsed([('r', '2026-10-01T05:00:00Z', counts())])
        result = build_activity([session], period={'start': '2026-09-01', 'end': '2026-09-30'},
                                timezone_name='America/Montevideo',
                                timezone_changes=[{'from': '2026-09-13',
                                                   'timezone': 'America/Los_Angeles'}])['tokens']
        self.assertEqual(result['total_tokens'], 120)

    def test_missing_token_records_are_unavailable(self):
        result = aggregate([parsed([])])['tokens']
        self.assertFalse(result['available'])
        self.assertIsNone(result['total_tokens'])

    def test_conflicting_and_invalid_usage_is_excluded(self):
        records = [('conflict', '2026-09-07T12:00:00Z', counts()),
                   ('conflict', '2026-09-07T12:00:00Z', counts(200)),
                   ('bad', '2026-09-07T12:00:00Z', counts(-1)),
                   ('ok', '2026-09-08T12:00:00Z', counts())]
        result = aggregate([parsed(records)])['tokens']
        self.assertEqual(result['total_tokens'], 120)
        self.assertEqual(result['conflicting_responses'], 1)
        self.assertEqual(result['invalid_records'], 1)

    def test_tokens_reach_html_and_metrics_with_coverage(self):
        activity = aggregate([parsed([('r', '2026-09-07T12:00:00Z', counts())])])
        data = make_data(codex={**CODEX_AVAILABLE, 'tokens': activity['tokens']})
        report = generate_report(data)
        self.assertIn('120', report)
        self.assertIn('2026-09-07', report)
        self.assertIn('Cached input', report)
        self.assertEqual(build_metrics(data)['tokens']['total_tokens'], 120)

    def test_contribution_evidence_precedes_runtime_and_escapes_subjects(self):
        from tests.test_generate_report import commit
        report = generate_report(make_data(commits=[commit(subject='feat: <script>bad</script>')]))
        self.assertLess(report.index('Contribution overview'), report.index('Recorded Codex runtime'))
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', report)
        self.assertIn('Merge and deployment not verified', report)


if __name__ == '__main__':
    unittest.main()
