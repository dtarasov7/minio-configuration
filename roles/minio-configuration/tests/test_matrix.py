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
    return {row['resource']: row for row in csv.DictReader(io.StringIO(report['csv']), delimiter=';')}


class MatrixTests(unittest.TestCase):
    def test_reader_uses_lowercase_on_prefix_created_by_another_users_policy(self):
        snapshot = configuration([statement('s3:ListBucket', 'arn:aws:s3:::data'), statement()])
        snapshot['users'].append({'name': 'writer', 'status': 'enabled', 'policies': ['writer']})
        snapshot['policies']['writer'] = {'Statement': [statement('s3:*', 'arn:aws:s3:::data/other/*')]}
        result = table(snapshot)
        self.assertEqual(result['data/*']['u:alice'], 'L  R  -  -')
        self.assertEqual(result['data/other/*']['u:alice'], 'l  r  -  -')
        self.assertEqual(result['data/other/*']['u:writer'], '-  R  W  D')

    def test_explicit_allow_wins_case_over_inherited_allow_in_any_order(self):
        broad = statement()
        narrow = statement(resource='arn:aws:s3:::data/other/*')
        for rules in ([broad, narrow], [narrow, broad]):
            result = table(configuration(rules))
            self.assertEqual(result['data/other/*']['u:alice'], '-  R  -  -')
        combined = statement(resource=['arn:aws:s3:::data/*', 'arn:aws:s3:::data/other/*'])
        self.assertEqual(table(configuration([combined]))['data/other/*']['u:alice'], '-  R  -  -')

    def test_denial_case_comes_from_winning_deny_not_allow(self):
        broad_deny = statement(Effect='Deny')
        narrow_allow = statement(resource='arn:aws:s3:::data/other/*')
        result = table(configuration([broad_deny, narrow_allow]))
        self.assertEqual(result['data/other/*']['u:alice'], '-  !r -  -')
        narrow_deny = dict(narrow_allow, Effect='Deny')
        for rules in ([broad_deny, narrow_deny], [narrow_deny, broad_deny]):
            self.assertEqual(table(configuration(rules))['data/other/*']['u:alice'], '-  !R -  -')

    def test_prefix_condition_is_explicit_on_its_range_and_inherited_below(self):
        rule = statement('s3:ListBucket', 'arn:aws:s3:::data',
                         Condition={'StringLike': {'s3:prefix': ['other/*']}})
        child = statement('s3:DeleteObject', 'arn:aws:s3:::data/other/nested/*')
        result = table(configuration([rule, statement(), child]))
        self.assertEqual(result['data/other/*']['u:alice'], 'L  r  -  -')
        self.assertEqual(result['data/other/nested/*']['u:alice'], 'l  r  -  D')

    def test_unknown_uses_one_question_mark_in_the_fixed_action_slot(self):
        cases = [('s3:ListBucket', 'arn:aws:s3:::data', '?  -  -  -'),
                 ('s3:GetObject', 'arn:aws:s3:::data/*', '-  ?  -  -'),
                 ('s3:PutObject', 'arn:aws:s3:::data/*', '-  -  ?  -'),
                 ('s3:DeleteObject', 'arn:aws:s3:::data/*', '-  -  -  ?')]
        for action, resource, expected in cases:
            rule = statement(action, resource, Condition={'Bool': {'aws:SecureTransport': 'true'}})
            self.assertEqual(table(configuration([rule]))['data/*']['u:alice'], expected)

    def test_unknown_narrow_rule_does_not_mark_its_parent(self):
        rule = statement('s3:PutObject', 'arn:aws:s3:::data/private/*',
                         Condition={'Bool': {'aws:SecureTransport': 'true'}})
        result = table(configuration([rule]))
        self.assertEqual(result['data/*']['u:alice'], '-  -  -  -')
        self.assertEqual(result['data/private/*']['u:alice'], '-  -  ?  -')

    def test_narrow_permissions_are_not_summarized_on_parent_but_unknown_is_visible(self):
        partial = statement('s3:PutObject', 'arn:aws:s3:::data/reports/*')
        self.assertEqual(table(configuration([partial]))['data/*']['u:alice'], '-  -  -  -')
        self.assertEqual(table(configuration([partial]))['data/reports/*']['u:alice'], '-  -  W  -')
        unknown = statement('s3:PutObject', Condition={'Bool': {'aws:SecureTransport': 'true'}})
        self.assertEqual(table(configuration([unknown]))['data/*']['u:alice'], '-  -  ?  -')
        self.assertEqual(table(configuration([partial, unknown]))['data/*']['u:alice'], '-  -  ?  -')
        denial = statement('s3:PutObject', Effect='Deny')
        self.assertEqual(table(configuration([partial, unknown, denial]))['data/*']['u:alice'], '-  -  !W -')

    def test_partial_denial_without_allow_does_not_claim_partial_permission(self):
        denial = statement('s3:PutObject', 'arn:aws:s3:::data/private/*', Effect='Deny')
        result = table(configuration([denial]))
        self.assertEqual(result['data/*']['u:alice'], '-  -  -  -')
        self.assertEqual(result['data/private/*']['u:alice'], '-  -  !W -')

    def test_narrow_allow_deny_conflict_is_displayed_only_in_its_own_row(self):
        rules = [statement('s3:PutObject', 'arn:aws:s3:::data/reports/*'),
                 statement('s3:PutObject', 'arn:aws:s3:::data/reports/*', Effect='Deny')]
        self.assertEqual(table(configuration(rules))['data/*']['u:alice'], '-  -  -  -')
        self.assertEqual(table(configuration(rules))['data/reports/*']['u:alice'], '-  -  !W -')

    def test_disjoint_prefix_conditions_do_not_claim_partial_permission(self):
        rule = statement('s3:ListBucket', 'arn:aws:s3:::data', Condition={
            'StringLike': {'s3:prefix': ['other/*']},
            'StringEquals': {'s3:prefix': ['reports/']}})
        result = table(configuration([rule]))
        for row in result.values():
            self.assertEqual(row['u:alice'], '-  -  -  -')

    def test_prefix_condition_allows_listing_only_inside_selected_range(self):
        rules = [statement(), statement('s3:*', 'arn:aws:s3:::data/other/*'),
                 statement('s3:ListBucket', 'arn:aws:s3:::data',
                           Condition={'StringLike': {'s3:prefix': ['other/*']}}),
                 statement(resource='arn:aws:s3:::data/outside/*')]
        result = table(configuration(rules))
        self.assertEqual(result['data/*']['u:alice'], '-  R  -  -')
        self.assertEqual(result['data/other/*']['u:alice'], 'L  R  W  D')
        self.assertEqual(result['data/outside/*']['u:alice'], '-  R  -  -')

    def test_prefix_condition_creates_rows_even_without_object_policies(self):
        rule = statement('s3:ListBucket', 'arn:aws:s3:::data',
                         Condition={'StringLike': {'s3:prefix': ['other/*', 'reports/*']}})
        result = table(configuration([rule]))
        self.assertEqual(result['data/other/*']['u:alice'], 'L  -  -  -')
        self.assertEqual(result['data/reports/*']['u:alice'], 'L  -  -  -')
        self.assertEqual(result['data/*']['u:alice'], '-  -  -  -')

    def test_exact_prefix_request_does_not_imply_all_nested_prefix_requests(self):
        rule = statement('s3:ListBucket', 'arn:aws:s3:::data',
                         Condition={'StringEquals': {'s3:prefix': 'other/'}})
        child = statement(resource='arn:aws:s3:::data/other/*')
        result = table(configuration([rule, child]))
        self.assertEqual(result['data/other/']['u:alice'], 'L  r  -  -')
        self.assertEqual(result['data/other/*']['u:alice'], '-  R  -  -')

    def test_prefix_values_use_or_and_operators_use_and(self):
        rule = statement('s3:ListBucket', 'arn:aws:s3:::data', Condition={
            'StringLike': {'s3:prefix': ['other/*', 'reports/*']},
            'StringEquals': {'s3:prefix': ['other/', 'elsewhere/']}})
        result = table(configuration([rule]))
        self.assertEqual(result['data/other/']['u:alice'], 'L  -  -  -')
        self.assertEqual(result['data/elsewhere/']['u:alice'], '-  -  -  -')
        self.assertEqual(result['data/reports/*']['u:alice'], '-  -  -  -')

    def test_conditional_deny_overrides_only_its_prefix(self):
        rules = [statement('s3:ListBucket', 'arn:aws:s3:::data'),
                 statement('s3:ListBucket', 'arn:aws:s3:::data', Effect='Deny',
                           Condition={'StringLike': {'s3:prefix': ['private/*']}}),
                 statement(resource='arn:aws:s3:::data/public/*')]
        result = table(configuration(rules))
        self.assertEqual(result['data/*']['u:alice'], 'L  -  -  -')
        self.assertEqual(result['data/private/*']['u:alice'], '!L -  -  -')
        self.assertEqual(result['data/public/*']['u:alice'], 'l  R  -  -')

    def test_anonymous_prefix_condition_and_bucket_isolation(self):
        rule = statement('s3:ListBucket', '*', Principal='*',
                         Condition={'StringLike': {'s3:prefix': ['public/*']}})
        snapshot = configuration(anonymous=[rule])
        snapshot['buckets'].append({'name': 'other', 'policy': {'Statement': []}})
        result = table(snapshot)
        self.assertEqual(result['data/public/*']['anonymous'], 'L  -  -  -')
        self.assertEqual(result['other/*']['anonymous'], '-  -  -  -')
        self.assertNotIn('other/public/*', result)

    def test_other_conditions_and_non_list_actions_remain_unknown(self):
        for condition in [
                {'StringNotLike': {'s3:prefix': ['other/*']}},
                {'StringLike': {'s3:prefix': ['other/*'], 'aws:username': ['alice']}},
                {'StringLike': {'s3:prefix': ['other/*/*']}},
                {'StringLike': {'s3:prefix': ['${aws:username}/*']}},
                {'StringEquals': {'s3:prefix': ['other/*']}}]:
            rule = statement('s3:ListBucket', 'arn:aws:s3:::data', Condition=condition)
            result = MATRIX.access_matrix(configuration([rule]))
            self.assertEqual(table(configuration([rule]))['data/*']['u:alice'], '?  -  -  -')
            self.assertIn('Condition is not evaluated', result['notes'])
        rule = statement(Condition={'StringLike': {'s3:prefix': ['other/*']}})
        self.assertEqual(table(configuration([rule]))['data/*']['u:alice'], '-  ?  -  -')

    def test_bucket_listing_is_inherited_on_object_rows_but_not_granted_by_object_arn(self):
        snapshot = configuration([statement('s3:ListBucket', 'arn:aws:s3:::data'), statement(),
                                  statement('s3:*', 'arn:aws:s3:::data/reports/*')])
        result = table(snapshot)
        self.assertEqual(set(result), {'data/*', 'data/reports/*'})
        self.assertEqual(result['data/*']['u:alice'], 'L  R  -  -')
        self.assertEqual(result['data/reports/*']['u:alice'], 'l  R  W  D')
        only_object = table(configuration([statement('s3:*')]))
        self.assertEqual(only_object['data/*']['u:alice'], '-  R  W  D')

    def test_two_direct_policies_add_prefix_row_and_leave_other_buckets_unchanged(self):
        for prefix in ('reports/*', 'reports*'):
            snapshot = configuration([statement()])
            snapshot['buckets'].append({'name': 'other', 'policy': {'Statement': []}})
            snapshot['policies']['prefix'] = {'Statement': [statement('s3:*', 'arn:aws:s3:::data/' + prefix)]}
            snapshot['users'][0]['policies'].append('prefix')
            result = table(snapshot)
            self.assertEqual(result['data/' + prefix]['u:alice'], '-  R  W  D')
            self.assertEqual(result['data/*']['u:alice'], '-  R  -  -')
            self.assertEqual(result['other/*']['u:alice'], '-  -  -  -')

    def test_unsupported_object_mask_keeps_uncertainty_in_its_bucket(self):
        snapshot = configuration([statement(), statement('s3:*', 'arn:aws:s3:::data/reports/*/file*')])
        snapshot['buckets'].append({'name': 'other', 'policy': {'Statement': []}})
        result = table(snapshot)
        self.assertEqual(result['data/*']['u:alice'], '-  ?  ?  ?')
        self.assertEqual(result['other/*']['u:alice'], '-  -  -  -')

    def test_unsupported_bucket_mask_does_not_affect_nonmatching_buckets(self):
        for resource, expected in [('arn:aws:s3:::data-*/*', '-  ?  ?  ?'),
                                   ('arn:aws:s3:::data-*', '?  ?  ?  ?')]:
            snapshot = configuration([statement('s3:*', resource)])
            snapshot['buckets'].append({'name': 'data-one', 'policy': {'Statement': []}})
            result = table(snapshot)
            self.assertEqual(result['data/*']['u:alice'], '-  -  -  -')
            self.assertEqual(result['data-one/*']['u:alice'], expected)

    def test_delete_position_is_fixed_for_allow_deny_and_uncertainty(self):
        for rule, expected in [
                (statement('s3:DeleteObject'), '-  -  -  D'),
                (statement(['s3:GetObject', 's3:PutObject', 's3:DeleteObject']), '-  R  W  D'),
                (statement('s3:DeleteObject', Effect='Deny'), '-  -  -  !D'),
                (statement('s3:DeleteObject', Condition={}), '-  -  -  ?')]:
            value = table(configuration([rule]))['data/*']['u:alice']
            self.assertEqual(value, expected)

    def test_action_mapping_and_listing_displayed_on_object_row(self):
        snapshot = configuration([statement('s3:*', '*')])
        result = table(snapshot)
        self.assertNotIn('data', result)
        self.assertEqual(result['data/*']['u:alice'], 'l  r  w  d')
        self.assertEqual(result['data/*']['anonymous'], '-  -  -  -')
        self.assertIn('Actions outside', MATRIX.access_matrix(snapshot)['notes'])

    def test_deny_overrides_across_policies_and_order_is_irrelevant(self):
        snapshot = configuration([statement()])
        snapshot['policies']['deny'] = {'Statement': statement(Effect='Deny')}
        snapshot['users'][0]['policies'].append('deny')
        self.assertEqual(table(snapshot)['data/*']['u:alice'], '-  !R -  -')
        for rules in ([statement(), statement(Effect='Deny')],
                      [statement(Effect='Deny'), statement()]):
            self.assertEqual(table(configuration(rules))['data/*']['u:alice'], '-  !R -  -')

    def test_nested_prefix_deny_and_exact_object_inherit_parent_allow(self):
        snapshot = configuration([statement(), statement(resource='arn:aws:s3:::data/private/*', Effect='Deny'),
                                  statement('s3:PutObject', 'arn:aws:s3:::data/private/file.txt')])
        result = table(snapshot)
        self.assertEqual(result['data/*']['u:alice'], '-  R  -  -')
        self.assertEqual(result['data/private/*']['u:alice'], '-  !R -  -')
        self.assertEqual(result['data/private/file.txt']['u:alice'], '-  !r W  -')

    def test_partial_allow_does_not_make_full_allow_uncertain(self):
        narrow = statement(resource='arn:aws:s3:::data/public/*')
        for rules in ([narrow, statement()], [statement(), narrow]):
            self.assertEqual(table(configuration(rules))['data/*']['u:alice'], '-  R  -  -')

    def test_conditions_never_become_unconditional_permissions_or_denials(self):
        for effect in ('Allow', 'Deny'):
            conditional = statement(Effect=effect, Condition={'Bool': {'aws:SecureTransport': 'true'}})
            result = MATRIX.access_matrix(configuration([conditional]))
            self.assertEqual(table(configuration([conditional]))['data/*']['u:alice'], '-  ?  -  -')
            self.assertIn('Condition is not evaluated', result['notes'])
        rules = [statement(Effect='Deny'), statement(Condition={})]
        self.assertEqual(table(configuration(rules))['data/*']['u:alice'], '-  !R -  -')

    def test_unsupported_resources_and_negative_elements_are_visible(self):
        rules = [statement(resource='arn:aws:s3:::project-*/*'),
                 {'Effect': 'Deny', 'NotAction': 's3:GetObject', 'NotResource': 'arn:aws:s3:::other/*'}]
        result = MATRIX.access_matrix(configuration(rules))
        self.assertEqual(table(configuration(rules))['data/*']['u:alice'], '?  ?  ?  ?')
        self.assertIn('NotAction/NotResource', result['notes'])
        self.assertIn('unsupported', result['notes'])
        self.assertIn('arn:aws:s3:::project-*/*', result['notes'])

    def test_out_of_scope_action_does_not_silently_become_write(self):
        snapshot = configuration([statement('s3:AbortMultipartUpload')])
        self.assertEqual(table(snapshot)['data/*']['u:alice'], '-  -  -  -')
        self.assertEqual(MATRIX.access_matrix(snapshot)['warning_count'], 1)

    def test_public_principals_and_anonymous_policy_isolation(self):
        for principal in ('*', {'AWS': '*'}, {'AWS': ['*']}):
            snapshot = configuration(anonymous=[statement(Principal=principal)])
            result = table(snapshot)
            self.assertEqual(result['data/*']['anonymous'], '-  R  -  -')
            self.assertEqual(result['data/*']['u:alice'], '-  -  -  -')
        snapshot['buckets'].append({'name': 'other', 'policy': {'Statement': []}})
        snapshot['buckets'][0]['policy']['Statement'][0]['Resource'] = '*'
        self.assertEqual(table(snapshot)['other/*']['anonymous'], '-  -  -  -')

    def test_anonymous_conditions_denials_and_unsupported_principals(self):
        for extra in ({'Condition': {'Bool': {'aws:SecureTransport': 'true'}}},
                      {'Principal': {'AWS': 'specific-user'}}, {'NotPrincipal': '*'}):
            rule = statement(Principal='*')
            rule.update(extra)
            self.assertEqual(table(configuration(anonymous=[rule]))['data/*']['anonymous'], '-  ?  -  -')
        rules = [statement(Principal='*'), statement(Principal='*', Effect='Deny')]
        self.assertEqual(table(configuration(anonymous=rules))['data/*']['anonymous'], '-  !R -  -')

    def test_disabled_and_no_direct_policy_users_and_column_collision(self):
        snapshot = configuration([statement()])
        snapshot['users'] += [{'name': 'anonymous', 'status': 'enabled', 'policies': []},
                              {'name': 'off', 'status': 'disabled', 'policies': ['direct']}]
        result = table(snapshot)['data/*']
        self.assertEqual(result['u:anonymous'], '-  -  -  -')
        self.assertEqual(result['u:off'], 'DISABLED')
        self.assertIn('anonymous', result)

    def test_csv_escaping_sorting_source_immutability_and_empty_cluster(self):
        snapshot = configuration([statement(resource='arn:aws:s3:::data/a;"b.txt')])
        snapshot['users'][0]['name'] = 'имя;"x'
        before = copy.deepcopy(snapshot)
        result = MATRIX.access_matrix(snapshot)
        rows = list(csv.reader(io.StringIO(result['csv']), delimiter=';'))
        self.assertEqual(rows[0][-1], 'u:имя;"x')
        self.assertEqual(rows[-1][2], 'data/a;"b.txt')
        self.assertEqual(snapshot, before)
        snapshot.update(buckets=[], users=[])
        self.assertEqual(MATRIX.access_matrix(snapshot)['csv'], 'bucket;scope;resource;anonymous\n')

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
