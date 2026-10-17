import importlib.util
import json
from pathlib import Path
import unittest

import yaml

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('snapshot', ROOT / 'library/minio_configuration_snapshot.py')
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)

READ = {'Version': '2012-10-17', 'Statement': [
    {'Sid': 'ReadObjects', 'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': ['arn:aws:s3:::project-*/public/*']},
    {'Sid': 'NoCreateBucket', 'Effect': 'Deny', 'Action': ['s3:CreateBucket'], 'Resource': ['arn:aws:s3:::*']}]}
ANONYMOUS = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Allow', 'Principal': {'AWS': ['*']}, 'Action': ['s3:GetObject'],
     'Resource': ['arn:aws:s3:::public/data.txt']}]}


class FakeModule:
    params = {'binary': '/mc', 'alias': 'local'}

    def __init__(self):
        self.calls = []
        self.responses = {
            ('ls', 'local'): [{'key': 'public/'}, {'key': 'private/'}],
            ('anonymous', 'get-json', 'local/public'): [{'anonymous': ANONYMOUS, 'permission': 'custom'}],
            ('anonymous', 'get-json', 'local/private'): [{'permission': 'private'}],
            ('version', 'info', 'local/public'): [{'versioning': {'status': 'Enabled'}}],
            ('version', 'info', 'local/private'): [{'versioning': {'status': ''}}],
            ('admin', 'user', 'list', 'local'): [{'accessKey': 'reader'}, {'accessKey': 'disabled'}],
            ('admin', 'user', 'info', 'local', 'reader'): [{'userStatus': 'enabled', 'policyName': 'read,deny', 'memberOf': [{'name': 'staff', 'policies': ['read']}]}],
            ('admin', 'user', 'info', 'local', 'disabled'): [{'userStatus': 'disabled'}],
            ('admin', 'group', 'list', 'local'): [{'groups': ['staff']}],
            ('admin', 'group', 'info', 'local', 'staff'): [
                {'groupStatus': 'disabled', 'groupPolicy': 'read', 'members': ['reader']}],
            ('admin', 'policy', 'list', 'local'): [{'policy': name} for name in ['read', 'deny', 'unused']],
            ('admin', 'policy', 'info', 'local', 'unused'): [{'policyInfo': {'policy': ANONYMOUS}}],
            ('admin', 'policy', 'info', 'local', 'read'): [{'policyInfo': {'policy': READ}}],
            ('admin', 'policy', 'info', 'local', 'deny'): [{'policyInfo': {'policy': READ}}],
        }

    def run_command(self, command):
        self.calls.append(command)
        records = self.responses[tuple(command[2:])]
        output = '\n'.join(json.dumps(record, indent=2) for record in records)
        return 0, output, ''


class SnapshotTests(unittest.TestCase):
    def test_snapshot_preserves_policies_status_and_membership_without_secrets(self):
        module = FakeModule()
        result = SNAPSHOT.Snapshot(module).collect()
        self.assertEqual(result['minio_configuration_backets'], [
            {'name': 'private', 'versioning': False, 'anonymous': 'none'},
            {'name': 'public', 'versioning': True, 'anonymous_policy': ANONYMOUS}])
        self.assertEqual(result['minio_configuration_users'][0],
                         {'name': 'disabled', 'status': 'disabled', 'statements': [], 'groups': []})
        exported_rules = result['minio_configuration_users'][1]['statements']
        self.assertEqual(len(exported_rules), 4)
        self.assertEqual(len({rule['Sid'] for rule in exported_rules}), 4)
        self.assertEqual(result['minio_configuration_groups'][0]['status'], 'disabled')
        self.assertEqual(result['minio_configuration_users'][1]['groups'], ['staff'])
        self.assertEqual(result['minio_configuration_groups'][0]['statements'], READ['Statement'])
        self.assertEqual(result['minio_configuration_exported_policies'],
                         {'read': READ, 'deny': READ, 'unused': ANONYMOUS})
        self.assertNotIn('secret_key', json.dumps(result))
        for command in module.calls:
            self.assertFalse({'set', 'add', 'remove', 'create', 'attach', 'detach'} & set(command))

    def test_bucket_name_listing_only_reads_names_and_accepts_pretty_json(self):
        module = FakeModule()
        names = SNAPSHOT.Snapshot(module).bucket_names()
        self.assertEqual(names, ['public', 'private'])
        self.assertEqual(module.calls, [['/mc', '--json', 'ls', 'local']])

    def test_custom_alias_used_in_every_snapshot_command(self):
        module = FakeModule()
        module.params = {'binary': '/mc', 'alias': 'production'}
        module.responses = {tuple(value.replace('local', 'production') for value in key): response
                            for key, response in module.responses.items()}
        SNAPSHOT.Snapshot(module).collect()
        for command in module.calls:
            self.assertFalse(any(value == 'local' or value.startswith('local/') for value in command))
            self.assertTrue(any(value == 'production' or value.startswith('production/') for value in command))

    def test_empty_server(self):
        module = FakeModule()
        module.responses[('ls', 'local')] = []
        module.responses[('admin', 'user', 'list', 'local')] = []
        module.responses[('admin', 'group', 'list', 'local')] = [{'status': 'success'}]
        module.responses[('admin', 'policy', 'list', 'local')] = []
        result = SNAPSHOT.Snapshot(module).collect()
        self.assertEqual(result['minio_configuration_exported_policies'], {})
        self.assertEqual(result['minio_configuration_users'], [])
        self.assertEqual(result['minio_configuration_backets'], [])

    def test_missing_policy_must_not_be_exported_as_private(self):
        module = FakeModule()
        module.responses[('anonymous', 'get-json', 'local/public')] = [{'permission': 'custom'}]
        with self.assertRaisesRegex(ValueError, 'Missing anonymous policy'):
            SNAPSHOT.Snapshot(module).collect()

    def test_error_response_is_fatal(self):
        module = FakeModule()
        module.responses[('ls', 'local')] = [{'status': 'error', 'error': 'AccessDenied'}]
        with self.assertRaisesRegex(ValueError, 'reported an error'):
            SNAPSHOT.Snapshot(module).collect()

    def test_failed_command_is_fatal(self):
        module = FakeModule()
        module.run_command = lambda command: (1, '', 'AccessDenied')
        with self.assertRaisesRegex(ValueError, 'AccessDenied'):
            SNAPSHOT.Snapshot(module).collect()

    def test_malformed_json_is_fatal(self):
        with self.assertRaises(ValueError):
            SNAPSHOT.decode_stream('{"status":"success"}\nnot json')

    def test_pretty_and_compact_streams(self):
        self.assertEqual(SNAPSHOT.decode_stream('{\n"a":1\n}\n{"a":2}\n'), [{'a': 1}, {'a': 2}])

    def test_policy_document_formats(self):
        for response in [READ, {'policy': READ}, {'policyInfo': {'policy': READ}}, {'policyInfo': {'Policy': READ}},
                         {'policyInfo': {'policy': json.dumps(READ)}}]:
            self.assertEqual(SNAPSHOT.policy_document(response), READ)
        with self.assertRaises(ValueError):
            SNAPSHOT.policy_document({'policy': 'readonly'})


class PolicyTests(unittest.TestCase):
    def render(self, statement):
        environment = Environment()
        environment.filters['to_nice_json'] = json.dumps
        template_text = (ROOT / 'templates/policy.json.j2').read_text()
        template = environment.from_string(template_text)
        return json.loads(template.render(item={'statement': statement}))

    def test_each_rule_has_its_own_exact_document(self):
        for statement in READ['Statement']:
            result = self.render(statement)
            self.assertEqual(result, {'Version': '2012-10-17', 'Statement': [statement]})

    def test_default_users_preserve_read_and_write_permissions(self):
        defaults = yaml.safe_load((ROOT / 'defaults/main.yml').read_text())
        users = defaults['minio_configuration_users']
        readonly = self.render(users[0]['statements'][1])
        readwrite = self.render(users[1]['statements'][1])
        self.assertEqual(readonly['Statement'][0]['Action'], ['s3:GetObject'])
        self.assertEqual(set(readwrite['Statement'][0]['Action']),
                         {'s3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:AbortMultipartUpload'})


FILTER_SPEC = importlib.util.spec_from_file_location('policies', ROOT / 'filter_plugins/minio_configuration_policies.py')
POLICIES = importlib.util.module_from_spec(FILTER_SPEC)
FILTER_SPEC.loader.exec_module(POLICIES)


class PolicyIdentityTests(unittest.TestCase):
    def test_repeated_sid_across_owners_and_owner_types_is_allowed(self):
        users = [{'name': 'alice', 'statements': READ['Statement']},
                 {'name': 'bob', 'statements': READ['Statement']}]
        groups = [{'name': 'alice', 'statements': READ['Statement']}]
        definitions = POLICIES.policy_definitions(users, groups)
        names = [definition['name'] for definition in definitions]
        self.assertEqual(len(set(names)), 6)
        self.assertIn('policy-user-alice-ReadObjects', names)
        self.assertIn('policy-grp-alice-ReadObjects', names)

    def test_duplicate_sid_within_owner_is_rejected(self):
        with self.assertRaisesRegex(Exception, 'Duplicate Sid'):
            POLICIES.policy_definitions([{'name': 'alice', 'statements': [READ['Statement'][0]] * 2}], [])
        with self.assertRaisesRegex(Exception, 'Duplicate Sid'):
            POLICIES.policy_definitions([], [{'name': 'alice', 'statements': [READ['Statement'][0]] * 2}])

    def test_missing_and_unsafe_sid_are_rejected(self):
        for sid in [None, '', 'Read-Objects', 'Read/Objects', 123]:
            statement = dict(READ['Statement'][0], Sid=sid)
            with self.assertRaisesRegex(Exception, 'Sid'):
                POLICIES.policy_definitions([{'name': 'alice', 'statements': [statement]}], [])

    def test_policy_filename_rejects_path_separators_and_control_characters(self):
        for owner in ['../alice', 'team/alice', 'team\\alice', 'alice\x00', 'alice\n']:
            with self.subTest(owner=owner):
                with self.assertRaisesRegex(Exception, 'Policy filename'):
                    POLICIES.policy_name('user', owner, 'Read')

    def test_policy_filename_length_is_checked_in_utf8_bytes(self):
        overhead = len('policy-user--Read.json'.encode('utf-8'))
        maximum_owner_bytes = 255 - overhead
        name = POLICIES.policy_name('user', 'a' * maximum_owner_bytes, 'Read')
        self.assertEqual(len((name + '.json').encode('utf-8')), 255)
        for owner in ['a' * (maximum_owner_bytes + 1), 'я' * maximum_owner_bytes]:
            with self.subTest(owner=owner):
                with self.assertRaisesRegex(Exception, '255 UTF-8 bytes'):
                    POLICIES.policy_name('user', owner, 'Read')
        self.assertEqual(POLICIES.policy_name('user', 'имя', 'Read'),
                         'policy-user-имя-Read')

    def test_empty_rules_create_no_policy(self):
        self.assertEqual(POLICIES.policy_definitions([{'name': 'alice', 'statements': []}], []), [])

    def test_export_assigns_stable_unique_sids_and_does_not_modify_source(self):
        rule = {'Effect': 'Allow', 'Action': ['s3:GetObject'], 'Resource': ['arn:aws:s3:::data/*']}
        documents = {'one': {'Statement': [rule, dict(rule, Sid='Read')]},
                     'two': {'Statement': [dict(rule, Sid='Read')]}}
        first = SNAPSHOT.owner_statements(['one', 'two'], documents)
        self.assertEqual(first, SNAPSHOT.owner_statements(['one', 'two'], documents))
        self.assertEqual(len({statement['Sid'] for statement in first}), 3)
        self.assertNotIn('Sid', documents['one']['Statement'][0])

    def test_snapshot_collects_shared_direct_owners(self):
        assignments = SNAPSHOT.Snapshot(FakeModule()).collect_assignments()
        self.assertEqual(assignments['read'], [{'kind': 'user', 'name': 'reader'},
                                              {'kind': 'grp', 'name': 'staff'}])


if __name__ == '__main__':
    unittest.main()
