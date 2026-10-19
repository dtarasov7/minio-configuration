import copy
import csv
import importlib.util
import io
from pathlib import Path
import unittest

from test_snapshot import FakeModule, SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('matrix', ROOT / 'filter_plugins/minio_configuration_matrix.py')
MATRIX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATRIX)


def statement(action='s3:GetObject', resource='arn:aws:s3:::data/*', **fields):
    return dict({'Effect': 'Allow', 'Action': action, 'Resource': resource}, **fields)


def configuration(rules=None, anonymous=None):
    return {'alias': 'production', 'started_at': 'start', 'finished_at': 'end',
            'buckets': [{'name': 'data', 'policy': {'Statement': anonymous or []}}],
            'users': [{'name': 'alice', 'status': 'enabled', 'policies': ['direct']}],
            'policies': {'direct': {'Statement': rules or []}}}


def table(snapshot):
    report = MATRIX.access_matrix(snapshot)
    return {row['resource']: row for row in csv.DictReader(io.StringIO(report['csv']))}


class MatrixTests(unittest.TestCase):
    def test_action_mapping_and_bucket_object_separation(self):
        snapshot = configuration([statement('s3:*', '*')])
        result = table(snapshot)
        self.assertEqual(result['data']['user:alice'], 'L')
        self.assertEqual(result['data/*']['user:alice'], 'R W D')
        self.assertEqual(result['data/*']['anonymous'], '—')
        self.assertIn('Actions outside', MATRIX.access_matrix(snapshot)['notes'])

    def test_deny_overrides_across_policies_and_order_is_irrelevant(self):
        snapshot = configuration([statement()])
        snapshot['policies']['deny'] = {'Statement': statement(Effect='Deny')}
        snapshot['users'][0]['policies'].append('deny')
        self.assertEqual(table(snapshot)['data/*']['user:alice'], '!R')
        for rules in ([statement(), statement(Effect='Deny')],
                      [statement(Effect='Deny'), statement()]):
            self.assertEqual(table(configuration(rules))['data/*']['user:alice'], '!R')

    def test_nested_prefix_deny_and_exact_object_inherit_parent_allow(self):
        snapshot = configuration([statement(), statement(resource='arn:aws:s3:::data/private/*', Effect='Deny'),
                                  statement('s3:PutObject', 'arn:aws:s3:::data/private/file.txt')])
        result = table(snapshot)
        self.assertEqual(result['data/*']['user:alice'], 'R? W?')
        self.assertEqual(result['data/private/*']['user:alice'], '!R W?')
        self.assertEqual(result['data/private/file.txt']['user:alice'], '!R W')

    def test_partial_allow_does_not_make_full_allow_uncertain(self):
        narrow = statement(resource='arn:aws:s3:::data/public/*')
        for rules in ([narrow, statement()], [statement(), narrow]):
            self.assertEqual(table(configuration(rules))['data/*']['user:alice'], 'R')

    def test_conditions_never_become_unconditional_permissions_or_denials(self):
        for effect in ('Allow', 'Deny'):
            conditional = statement(Effect=effect, Condition={'Bool': {'aws:SecureTransport': 'true'}})
            result = MATRIX.access_matrix(configuration([conditional]))
            self.assertEqual(table(configuration([conditional]))['data/*']['user:alice'], 'R?')
            self.assertIn('Condition is not evaluated', result['notes'])
        rules = [statement(Effect='Deny'), statement(Condition={})]
        self.assertEqual(table(configuration(rules))['data/*']['user:alice'], '!R')

    def test_unsupported_resources_and_negative_elements_are_visible(self):
        rules = [statement(resource='arn:aws:s3:::project-*/*'),
                 {'Effect': 'Deny', 'NotAction': 's3:GetObject', 'NotResource': 'arn:aws:s3:::other/*'}]
        result = MATRIX.access_matrix(configuration(rules))
        self.assertEqual(table(configuration(rules))['data/*']['user:alice'], 'R? W? D?')
        self.assertIn('NotAction/NotResource', result['notes'])
        self.assertIn('unsupported', result['notes'])

    def test_out_of_scope_action_does_not_silently_become_write(self):
        snapshot = configuration([statement('s3:AbortMultipartUpload')])
        self.assertEqual(table(snapshot)['data/*']['user:alice'], '—')
        self.assertEqual(MATRIX.access_matrix(snapshot)['warning_count'], 1)

    def test_public_principals_and_anonymous_policy_isolation(self):
        for principal in ('*', {'AWS': '*'}, {'AWS': ['*']}):
            snapshot = configuration(anonymous=[statement(Principal=principal)])
            result = table(snapshot)
            self.assertEqual(result['data/*']['anonymous'], 'R')
            self.assertEqual(result['data/*']['user:alice'], '—')
        snapshot['buckets'].append({'name': 'other', 'policy': {'Statement': []}})
        snapshot['buckets'][0]['policy']['Statement'][0]['Resource'] = '*'
        self.assertEqual(table(snapshot)['other/*']['anonymous'], '—')

    def test_anonymous_conditions_denials_and_unsupported_principals(self):
        for extra in ({'Condition': {'Bool': {'aws:SecureTransport': 'true'}}},
                      {'Principal': {'AWS': 'specific-user'}}, {'NotPrincipal': '*'}):
            rule = statement(Principal='*')
            rule.update(extra)
            self.assertEqual(table(configuration(anonymous=[rule]))['data/*']['anonymous'], 'R?')
        rules = [statement(Principal='*'), statement(Principal='*', Effect='Deny')]
        self.assertEqual(table(configuration(anonymous=rules))['data/*']['anonymous'], '!R')

    def test_disabled_and_no_direct_policy_users_and_column_collision(self):
        snapshot = configuration([statement()])
        snapshot['users'] += [{'name': 'anonymous', 'status': 'enabled', 'policies': []},
                              {'name': 'off', 'status': 'disabled', 'policies': ['direct']}]
        result = table(snapshot)['data/*']
        self.assertEqual(result['user:anonymous'], '—')
        self.assertEqual(result['user:off'], 'DISABLED')
        self.assertIn('anonymous', result)

    def test_csv_escaping_sorting_source_immutability_and_empty_cluster(self):
        snapshot = configuration([statement(resource='arn:aws:s3:::data/a,"b.txt')])
        snapshot['users'][0]['name'] = 'имя,"x'
        before = copy.deepcopy(snapshot)
        result = MATRIX.access_matrix(snapshot)
        rows = list(csv.reader(io.StringIO(result['csv'])))
        self.assertEqual(rows[0][-1], 'user:имя,"x')
        self.assertEqual(rows[-1][2], 'data/a,"b.txt')
        self.assertEqual(snapshot, before)
        snapshot.update(buckets=[], users=[])
        self.assertEqual(MATRIX.access_matrix(snapshot)['csv'], 'bucket,scope,resource,anonymous\n')

    def test_malformed_or_missing_policy_fails_instead_of_reporting_no_access(self):
        for document in ({'Statement': 'invalid'}, {}, {'Statement': [None]}):
            snapshot = configuration()
            snapshot['policies']['direct'] = document
            with self.assertRaisesRegex(Exception, 'Cannot build'):
                MATRIX.access_matrix(snapshot)


class MatrixCollectionTests(unittest.TestCase):
    def module(self):
        module = FakeModule()
        module.responses[('admin', 'user', 'list', 'local')] = [
            {'accessKey': 'reader', 'userStatus': 'enabled', 'policyName': 'read',
             'memberOf': [{'name': 'staff', 'policies': ['deny']}]},
            {'accessKey': 'disabled', 'userStatus': 'disabled', 'policyName': ''}]
        return module

    def test_collection_only_reads_direct_policies_and_preserves_identity(self):
        module = self.module()
        result = SNAPSHOT.Snapshot(module).collect_matrix()
        self.assertEqual(list(result['policies']), ['read'])
        self.assertEqual(result['policies']['read'], module.responses[('admin', 'policy', 'info', 'local', 'read')][0]['policyInfo']['policy'])
        self.assertEqual(result['users'][0], {'name': 'disabled', 'status': 'disabled', 'policies': []})
        self.assertEqual(len(result['buckets']), 2)
        self.assertNotIn('groups', result)
        self.assertLessEqual(result['started_at'], result['finished_at'])
        expected = [('ls', 'local'), ('anonymous', 'get-json', 'local/private'),
                    ('anonymous', 'get-json', 'local/public'), ('admin', 'user', 'list', 'local'),
                    ('admin', 'policy', 'info', 'local', 'read')]
        self.assertEqual([tuple(command[2:]) for command in module.calls], expected)

    def test_missing_anonymous_document_and_user_status_fail(self):
        module = self.module()
        module.responses[('anonymous', 'get-json', 'local/private')] = [{'permission': 'custom'}]
        with self.assertRaisesRegex(ValueError, 'Missing anonymous policy'):
            SNAPSHOT.Snapshot(module).collect_matrix()
        module = self.module()
        module.responses[('admin', 'user', 'list', 'local')][0]['userStatus'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown user status'):
            SNAPSHOT.Snapshot(module).collect_matrix()

    def test_policy_read_error_is_fatal(self):
        module = self.module()
        module.responses[('admin', 'policy', 'info', 'local', 'read')] = [{'status': 'error', 'error': 'AccessDenied'}]
        with self.assertRaisesRegex(ValueError, 'AccessDenied'):
            SNAPSHOT.Snapshot(module).collect_matrix()

    def test_empty_cluster_needs_no_policy_reads(self):
        module = self.module()
        module.responses[('ls', 'local')] = []
        module.responses[('admin', 'user', 'list', 'local')] = []
        result = SNAPSHOT.Snapshot(module).collect_matrix()
        self.assertEqual(result['users'], [])
        self.assertEqual(result['buckets'], [])
        self.assertEqual(result['policies'], {})
        self.assertEqual(len(module.calls), 2)

    def test_shared_direct_policy_is_only_read_once(self):
        module = self.module()
        module.responses[('admin', 'user', 'list', 'local')][1]['policyName'] = 'read'
        result = SNAPSHOT.Snapshot(module).collect_matrix()
        policy_calls = [command for command in module.calls if command[2:5] == ['admin', 'policy', 'info']]
        self.assertEqual(len(policy_calls), 1)
        self.assertEqual(result['users'][0]['policies'], ['read'])


if __name__ == '__main__':
    unittest.main()
