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
        arguments = dict(users_delete=False, buckets_delete=False,
                         protected_users=['reader'], policy_dir='/policies', tags=['dryrun'])
        arguments.update(options)
        return POLICIES.configuration_plan(self.current, self.assignments, users, groups,
                                           buckets or [], rules, **arguments)

    def test_new_user_and_bucket_and_password_redaction(self):
        user = {'name': 'new', 'secret_key': 'never-print-this', 'statements': READ['Statement']}
        plan = self.plan(users=[user], buckets=[{'name': 'new-bucket', 'versioning': True}])
        self.assertIn({'action': 'create_user', 'target': 'new', 'secret_key': '[REDACTED]'}, plan)
        self.assertIn({'action': 'ensure_bucket', 'target': 'new-bucket'}, plan)
        self.assertIn({'action': 'set_versioning', 'target': 'new-bucket', 'enabled': True}, plan)
        self.assertNotIn('never-print-this', json.dumps(plan))
        self.assertEqual(len([op for op in plan if op['action'] == 'create_or_update_policy']), 2)

    def test_versioning_uses_ansible_boolean_conversion(self):
        for value, expected in [('false', False), ('true', True), (False, False), (True, True)]:
            with self.subTest(value=value):
                plan = self.plan(buckets=[{'name': 'public', 'versioning': value}])
                operation = {'action': 'set_versioning', 'target': 'public', 'enabled': expected}
                self.assertIn(operation, plan)

    def test_deletion_respects_protected_users(self):
        plan = self.plan(users_delete=True, buckets_delete=True)
        deleted_users = [op['target'] for op in plan if op['action'] == 'remove_user']
        self.assertEqual(deleted_users, ['disabled'])
        deleted_buckets = [op['target'] for op in plan if op['action'] == 'remove_bucket']
        self.assertEqual(deleted_buckets, ['private', 'public'])

    def test_user_tag_omits_bucket_operations(self):
        plan = self.plan(users=[{'name': 'reader'}], buckets=[{'name': 'new-bucket'}], tags=['user'])
        self.assertFalse(any(op['action'] == 'ensure_bucket' for op in plan))
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

    def test_clean_only_plans_cleanup(self):
        users = [{'name': 'reader'}, {'name': 'disabled'}]
        plan = self.plan(users=users, buckets=[{'name': 'public'}], tags=['clean'])
        self.assertEqual(plan[0], {'action': 'remove_user', 'target': 'disabled'})
        self.assertFalse(any(op['action'].startswith('ensure_') for op in plan))
        self.assertIn({'action': 'remove_file', 'target': '/policies/anonymous-public.json'}, plan)

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
        self.assertIn({'action': 'ensure_bucket', 'target': 'new-bucket'}, plan)
        self.assertFalse(any(op['action'] in ['detach_policy', 'remove_group_member'] for op in plan))
        self.assertEqual(self.plan(tags=['clean'], skip_tags=['clean']), [])

    def test_config_scope_has_no_mutations(self):
        self.assertEqual(self.plan(tags=['config']), [])

    def test_dry_and_dryrun_select_the_same_full_plan(self):
        arguments = {'users': [{'name': 'reader'}], 'buckets': [{'name': 'new-bucket'}]}
        dry_plan = self.plan(tags=['dry'], **arguments)
        dryrun_plan = self.plan(tags=['dryrun'], **arguments)
        self.assertEqual(dry_plan, dryrun_plan)
        self.assertIn({'action': 'ensure_bucket', 'target': 'new-bucket'}, dry_plan)
        self.assertIn({'action': 'detach_policy', 'target': 'reader', 'kind': 'user', 'policy': 'read'}, dry_plan)


if __name__ == '__main__':
    unittest.main()
