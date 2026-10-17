"""Dryrun must describe the selected operations without exposing credentials."""
import json
import unittest

from test_snapshot import FakeModule, POLICIES, READ, SNAPSHOT


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SNAPSHOT.Snapshot(FakeModule())
        self.current = self.snapshot.collect()
        self.assignments = self.snapshot.collect_assignments()

    def plan(self, users=None, groups=None, buckets=None, **options):
        users = users or []
        groups = groups or []
        rules = POLICIES.policy_definitions(users, groups)
        arguments = dict(users_delete=False,
                         protected_users=['reader'], tags=['all'])
        arguments.update(options)
        return POLICIES.configuration_plan(self.current, self.assignments, users, groups,
                                           buckets or [], rules, **arguments)

    def test_new_user_and_bucket_and_password_redaction(self):
        user = {'name': 'new', 'secret_key': 'never-print-this', 'statements': READ['Statement']}
        plan = self.plan(users=[user], buckets=[{'name': 'new-bucket', 'versioning': True}])
        self.assertIn({'action': 'create_user', 'target': 'new', 'secret_key': '[REDACTED]'}, plan)
        self.assertIn({'action': 'create_bucket', 'target': 'new-bucket', 'versioning': True}, plan)
        self.assertNotIn('never-print-this', json.dumps(plan))
        self.assertEqual(len([op for op in plan if op['action'] == 'create_policy']), 2)

    def test_versioning_uses_ansible_boolean_conversion(self):
        for value, expected in [('false', False), ('true', True), (False, False), (True, True)]:
            with self.subTest(value=value):
                plan = self.plan(buckets=[{'name': 'public', 'versioning': value}])
                operation = {'action': 'set_versioning', 'target': 'public', 'enabled': expected}
                self.assertEqual(operation in plan, expected is False)

    def test_deletion_respects_protected_users(self):
        plan = self.plan(users_delete=True)
        deleted_users = [op['target'] for op in plan if op['action'] == 'remove_user']
        self.assertEqual(deleted_users, ['disabled'])
        deleted_buckets = [op['target'] for op in plan if op['action'] == 'remove_bucket']
        self.assertEqual(deleted_buckets, [])

    def test_buckets_are_never_removed(self):
        for tags in [['all'], ['backet'], ['user']]:
            for buckets in [[], [{'name': 'public'}]]:
                with self.subTest(tags=tags, buckets=buckets):
                    plan = self.plan(buckets=buckets, tags=tags)
                    self.assertFalse(any(op['action'] == 'remove_bucket' for op in plan))

    def test_user_tag_omits_bucket_operations(self):
        plan = self.plan(users=[{'name': 'reader'}], buckets=[{'name': 'new-bucket'}], tags=['user'])
        self.assertFalse(any(op['action'] == 'create_bucket' for op in plan))
        self.assertIn({'action': 'remove_group_member', 'target': 'staff', 'user': 'reader'}, plan)
        detached = [op['policy'] for op in plan if op['action'] == 'detach_policy']
        self.assertEqual(detached, ['deny', 'read'])

    def test_group_then_user_membership_is_not_planned_twice(self):
        users = [{'name': 'new', 'secret_key': 'secret123', 'groups': ['staff']}]
        plan = self.plan(users=users, groups=[{'name': 'staff'}])
        membership = {'action': 'add_group_member', 'target': 'staff', 'user': 'new'}
        self.assertEqual(plan.count(membership), 1)
        self.assertIn({'action': 'set_group_status', 'target': 'staff', 'status': 'enabled'}, plan)

    def test_existing_user_password_is_updated_without_secret_in_plan(self):
        plan = self.plan(users=[{'name': 'reader', 'secret_key': 'newsecret'}])
        self.assertIn({'action': 'update_user_password', 'target': 'reader', 'secret_key': '[REDACTED]'}, plan)
        self.assertNotIn('newsecret', json.dumps(plan))

    def test_new_user_without_password_is_rejected(self):
        with self.assertRaisesRegex(Exception, 'New user requires secret_key'):
            self.plan(users=[{'name': 'new'}])

    def test_new_empty_group_is_rejected(self):
        with self.assertRaisesRegex(Exception, 'cannot create an empty group'):
            self.plan(groups=[{'name': 'empty'}])

    def test_foreign_policy_owner_is_rejected(self):
        user = {'name': 'reader', 'statements': READ['Statement']}
        name = POLICIES.policy_name('user', 'reader', 'ReadObjects')
        self.assignments[name] = [{'kind': 'user', 'name': 'foreign'}]
        with self.assertRaisesRegex(Exception, 'assigned to another owner'):
            self.plan(users=[user])

    def test_skipped_tags_are_excluded_from_plan(self):
        plan = self.plan(users=[{'name': 'reader'}], buckets=[{'name': 'new-bucket'}],
                         skip_tags=['user'])
        self.assertIn({'action': 'create_bucket', 'target': 'new-bucket', 'versioning': False}, plan)
        self.assertFalse(any(op['action'] in ['detach_policy', 'remove_group_member'] for op in plan))
        self.assertEqual(self.plan(tags=['backet'], skip_tags=['backet']), [])

    def test_matching_cluster_state_produces_empty_summary(self):
        user = {'name': 'disabled', 'status': 'disabled'}
        buckets = self.current['minio_configuration_backets']
        plan = self.plan(users=[user], buckets=buckets)
        self.assertEqual(POLICIES.plan_summary(plan), {'add': [], 'change': [], 'delete': []})

    def test_existing_buckets_only_report_changed_settings(self):
        plan = self.plan(buckets=[{'name': 'private', 'anonymous': 'private'},
                                  {'name': 'public', 'versioning': False, 'anonymous': 'none'}])
        self.assertEqual(plan, [
            {'action': 'set_versioning', 'target': 'public', 'enabled': False},
            {'action': 'set_anonymous', 'target': 'public', 'preset': 'none'}])

    def test_existing_policies_are_compared_by_document(self):
        user = {'name': 'reader', 'groups': ['staff'], 'statements': READ['Statement']}
        definitions = POLICIES.policy_definitions([user], [])
        for rule in definitions:
            self.current['minio_configuration_exported_policies'][rule['name']] = {
                'Version': '2012-10-17', 'Statement': [rule['statement']]}
        self.assignments = {rule['name']: [{'kind': 'user', 'name': 'reader'}] for rule in definitions}
        self.assertEqual(self.plan(users=[user]), [])
        self.current['minio_configuration_exported_policies'][definitions[0]['name']] = {'Statement': []}
        plan = self.plan(users=[user])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]['action'], 'update_policy')

    def test_summary_groups_cluster_mutations_and_redacts_passwords(self):
        plan = self.plan(users=[{'name': 'new', 'secret_key': 'secret123', 'groups': ['new-group']}],
                         buckets=[{'name': 'new-bucket'}], users_delete=True)
        summary = POLICIES.plan_summary(plan)
        self.assertIn({'type': 'bucket', 'name': 'new-bucket', 'action': 'create_bucket',
                       'versioning': False}, summary['add'])
        self.assertIn({'type': 'group', 'name': 'new-group', 'action': 'create_group',
                       'members': ['new']}, summary['add'])
        self.assertEqual(summary['delete'], [{'type': 'user', 'name': 'disabled', 'action': 'remove_user'}])
        self.assertNotIn('secret123', json.dumps(summary))
        self.assertFalse(any(op['action'] in ['ensure_directory', 'write_policy_file'] for op in plan))

    def test_console_omits_documents_without_changing_the_saved_plan(self):
        user = {'name': 'new', 'secret_key': 'secret123', 'statements': READ['Statement']}
        summary = POLICIES.plan_summary(self.plan(users=[user]))
        original = json.dumps(summary)
        console = POLICIES.plan_console(summary)
        self.assertNotIn('document', json.dumps(console))
        self.assertIn('create_policy', json.dumps(console))
        self.assertIn('policy-user-new-ReadObjects', json.dumps(console))
        self.assertEqual(json.dumps(summary), original)
        self.assertIn('document', original)

    def seed_owner_policies(self, owner='old'):
        statements = [dict(READ['Statement'][0], Sid=sid) for sid in ['One', 'Two', 'Three']]
        self.current['minio_configuration_users'].append(
            {'name': owner, 'status': 'enabled', 'groups': [], 'statements': statements})
        for statement in statements:
            name = POLICIES.policy_name('user', owner, statement['Sid'])
            self.current['minio_configuration_exported_policies'][name] = {
                'Version': '2012-10-17', 'Statement': [statement]}
            self.assignments[name] = [{'kind': 'user', 'name': owner}]
        return statements

    def test_renamed_user_plans_old_policy_removal_and_three_new_policies(self):
        statements = self.seed_owner_policies()
        user = {'name': 'renamed', 'secret_key': 'secret123', 'statements': statements}
        original_assignments = json.dumps(self.assignments)
        plan = self.plan(users=[user], users_delete=True)
        removed = [op['target'] for op in plan if op['action'] == 'remove_policy']
        self.assertEqual(removed, ['policy-user-old-One', 'policy-user-old-Three', 'policy-user-old-Two'])
        self.assertIn({'action': 'remove_user', 'target': 'old'}, plan)
        self.assertEqual(len([op for op in plan if op['action'] == 'create_policy']), 3)
        self.assertEqual(len([op for op in plan if op['action'] == 'attach_policy']), 3)
        summary = POLICIES.plan_summary(plan)
        self.assertEqual(len([item for item in summary['delete'] if item['type'] == 'policy']), 3)
        self.assertEqual(json.dumps(self.assignments), original_assignments)

    def test_removed_user_policies_shared_with_surviving_owners_are_kept(self):
        self.seed_owner_policies()
        self.assignments['policy-user-old-One'].append({'kind': 'user', 'name': 'reader'})
        self.assignments['policy-user-old-Two'].append({'kind': 'grp', 'name': 'external'})
        plan = self.plan(users_delete=True)
        self.assertEqual([op['target'] for op in plan if op['action'] == 'remove_policy'],
                         ['policy-user-old-Three'])

    def test_policies_are_kept_when_old_user_is_preserved_or_protected(self):
        self.seed_owner_policies()
        for options in [{'users_delete': False},
                        {'users_delete': True, 'protected_users': ['reader', 'old']},
                        {'users_delete': True, 'tags': ['backet']},
                        {'users_delete': True, 'skip_tags': ['user']}]:
            with self.subTest(options=options):
                self.assertFalse(any(op['action'] == 'remove_policy' for op in self.plan(**options)))

    def test_changed_sid_detaches_and_removes_only_the_old_owned_policy(self):
        old = 'policy-user-reader-Old'
        self.assignments[old] = [{'kind': 'user', 'name': 'reader'}]
        self.current['minio_configuration_exported_policies'][old] = READ
        self.assignments['policy-user-reader-other-Read'] = [{'kind': 'user', 'name': 'reader'}]
        self.current['minio_configuration_exported_policies']['policy-user-orphan-Read'] = READ
        user = {'name': 'reader', 'groups': ['staff'], 'statements': [dict(READ['Statement'][0], Sid='New')]}
        plan = self.plan(users=[user])
        self.assertIn({'action': 'detach_policy', 'target': 'reader', 'kind': 'user', 'policy': old}, plan)
        self.assertEqual([op['target'] for op in plan if op['action'] == 'remove_policy'], [old])

    def test_removed_group_rule_policy_is_deleted_after_detachment(self):
        old = 'policy-grp-staff-Old'
        self.assignments[old] = [{'kind': 'grp', 'name': 'staff'}]
        self.current['minio_configuration_exported_policies'][old] = READ
        plan = self.plan(groups=[{'name': 'staff'}])
        self.assertIn({'action': 'remove_policy', 'target': old}, plan)

    def test_config_scope_has_no_mutations(self):
        self.assertEqual(self.plan(tags=['config']), [])

if __name__ == '__main__':
    unittest.main()
