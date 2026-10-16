"""Build owner-specific, per-statement MinIO policy definitions."""
import copy
import hashlib
import re

from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import to_bool


def policy_name(kind, owner, sid):
    if kind not in ('user', 'grp'):
        raise AnsibleFilterError('Policy owner kind must be user or grp')
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9]+', sid):
        raise AnsibleFilterError('Each user/group rule requires a non-empty alphanumeric Sid')
    return 'minio-configuration-{}-{}-{}'.format(kind, owner, sid)


def policy_definitions(users, groups):
    definitions = []
    for kind, owners in [('user', users), ('grp', groups)]:
        for owner in owners:
            statements = owner.get('statements', [])
            if not isinstance(statements, list):
                raise AnsibleFilterError('statements must be a list for {} {}'.format(kind, owner['name']))
            seen = set()
            for statement in statements:
                if not isinstance(statement, dict):
                    raise AnsibleFilterError('Each statement must be a mapping')
                sid = statement.get('Sid')
                name = policy_name(kind, owner['name'], sid)
                if sid in seen:
                    raise AnsibleFilterError('Duplicate Sid {} for {} {}'.format(sid, kind, owner['name']))
                seen.add(sid)
                definitions.append({'name': name, 'kind': kind, 'owner': owner['name'],
                                    'statement': statement})
    return definitions


def policy_names(owner, kind):
    owners = [owner]
    definitions = policy_definitions(owners if kind == 'user' else [],
                                     owners if kind == 'grp' else [])
    return [definition['name'] for definition in definitions]


def configuration_plan(current, assignments, users, groups, buckets, rules,
                       users_delete, buckets_delete, protected_users, policy_dir, tags, skip_tags=None):
    """Describe apply/clean operations using a read-only server snapshot."""
    operations = []
    existing_users = {user['name']: copy.deepcopy(user) for user in current['minio_configuration_users']}
    existing_groups = {group['name']: copy.deepcopy(group) for group in current['minio_configuration_groups']}
    existing_buckets = {bucket['name'] for bucket in current['minio_configuration_backets']}
    full_run = not tags or bool(set(tags) & {'all', 'tagged'})
    selected = set(tags)
    skipped = set(skip_tags or [])
    operation_tags = {'user', 'backet', 'install', 'clean', 'never', 'config', 'ssl', 'pre-req'}
    if selected.intersection({'dry', 'dryrun'}) and not selected.intersection(operation_tags):
        full_run = True

    def add(action, target, **details):
        operations.append(dict(action=action, target=target, **details))

    def policy_file(name):
        digest = hashlib.sha256(name.encode('utf-8')).hexdigest()
        return policy_dir + '/' + digest + '.json'

    def reconcile_policies(owner, kind):
        identity = {'kind': kind, 'name': owner['name']}
        attached = {name for name, owners in assignments.items() if identity in owners}
        desired = set(policy_names(owner, kind))
        for name in sorted(attached - desired):
            add('detach_policy', owner['name'], kind=kind, policy=name)
        for name in sorted(desired - attached):
            add('attach_policy', owner['name'], kind=kind, policy=name)

    if (selected.intersection({'clean', 'never'})) and not skipped.intersection({'clean', 'never'}):
        for user in users:
            if user['name'] not in protected_users:
                add('remove_user', user['name'])
        for bucket in buckets:
            add('remove_bucket', bucket['name'], force=True)
            add('remove_file', policy_dir + '/anonymous-' + bucket['name'] + '.json')
        for rule in rules:
            add('remove_file', policy_file(rule['name']))
        # A full run with clean explicitly selected applies changes before cleanup.
        if not full_run and not selected.intersection({'user', 'backet', 'install'}):
            return operations
        cleanup = operations
        operations = []
    else:
        cleanup = []

    needs_policy_dir = bool(rules) or any('anonymous_policy' in bucket for bucket in buckets)
    prepare_directory = full_run or bool(selected.intersection({'install', 'user', 'backet'}))
    if prepare_directory and not skipped.intersection({'install', 'user', 'backet'}) and (needs_policy_dir or 'install' in selected):
        add('ensure_directory', policy_dir, mode='0755')

    if (full_run or 'backet' in selected) and 'backet' not in skipped:
        for bucket in buckets:
            add('ensure_bucket', bucket['name'])
        for bucket in buckets:
            add('set_versioning', bucket['name'], enabled=to_bool(bucket.get('versioning', False)))
        if buckets_delete:
            desired_buckets = {bucket['name'] for bucket in buckets}
            for name in sorted(existing_buckets - desired_buckets):
                add('remove_bucket', name, force=True)
        for bucket in buckets:
            if 'anonymous' in bucket:
                add('set_anonymous', bucket['name'], preset=bucket['anonymous'])
            if 'anonymous_policy' in bucket:
                path = policy_dir + '/anonymous-' + bucket['name'] + '.json'
                add('write_policy_file', path, document=bucket['anonymous_policy'])
                add('set_anonymous_policy', bucket['name'], document=bucket['anonymous_policy'])

    if (full_run or 'user' in selected) and 'user' not in skipped:
        for rule in rules:
            owner = {'kind': rule['kind'], 'name': rule['owner']}
            foreign = [identity for identity in assignments.get(rule['name'], []) if identity != owner]
            if foreign:
                raise AnsibleFilterError('Policy {} is assigned to another owner'.format(rule['name']))
        for user in users:
            name = user['name']
            if name not in existing_users and 'secret_key' not in user:
                raise AnsibleFilterError('New user requires secret_key: ' + name)
            if 'secret_key' in user:
                action = 'update_user_password' if name in existing_users else 'create_user'
                add(action, name, secret_key='[REDACTED]')
            existing_users.setdefault(name, {'groups': [], 'status': 'enabled'})
        for rule in rules:
            document = {'Version': '2012-10-17', 'Statement': [rule['statement']]}
            add('write_policy_file', policy_file(rule['name']), document=document)
        for rule in rules:
            add('create_or_update_policy', rule['name'], document={
                'Version': '2012-10-17', 'Statement': [rule['statement']]})
        for group in groups:
            name = group['name']
            desired_members = set(group.get('members', []))
            desired_members.update(user['name'] for user in users if name in user.get('groups', []))
            if name not in existing_groups and not desired_members:
                raise AnsibleFilterError('mc cannot create an empty group: ' + name)
            actual_group = existing_groups.get(name, {'members': [], 'status': ''})
            actual_members = set(actual_group['members'])
            for member in sorted(desired_members - actual_members):
                add('add_group_member', name, user=member)
                if member in existing_users:
                    existing_users[member]['groups'].append(name)
            if 'members' in group:
                for member in sorted(actual_members - desired_members):
                    add('remove_group_member', name, user=member)
                    if member in existing_users and name in existing_users[member]['groups']:
                        existing_users[member]['groups'].remove(name)
            reconcile_policies(group, 'grp')
            status = group.get('status', 'enabled')
            if actual_group['status'] != status:
                add('set_group_status', name, status=status)
        for user in users:
            reconcile_policies(user, 'user')
        for user in users:
            name = user['name']
            actual_groups = set(existing_users[name]['groups'])
            desired_groups = set(user.get('groups', []))
            for group in sorted(actual_groups - desired_groups):
                add('remove_group_member', group, user=name)
            for group in sorted(desired_groups - actual_groups):
                add('add_group_member', group, user=name)
        for user in users:
            if 'status' in user:
                add('set_user_status', user['name'], status=user['status'])
        if users_delete:
            desired_users = {user['name'] for user in users}
            for name in sorted(set(existing_users) - desired_users - set(protected_users)):
                add('remove_user', name)
    return operations + cleanup


class FilterModule:
    def filters(self):
        return {'minio_configuration_policy_definitions': policy_definitions,
                'minio_configuration_policy_names': policy_names,
                'minio_configuration_plan': configuration_plan}
