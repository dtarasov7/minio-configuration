"""Build owner-specific, per-statement MinIO policy definitions."""
import copy
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
                       users_delete, protected_users, tags, skip_tags=None):
    """Describe planned cluster mutations using a read-only server snapshot."""
    operations = []
    existing_users = {user['name']: copy.deepcopy(user) for user in current['minio_configuration_users']}
    existing_groups = {group['name']: copy.deepcopy(group) for group in current['minio_configuration_groups']}
    existing_buckets = {bucket['name']: bucket for bucket in current['minio_configuration_backets']}
    existing_policies = current['minio_configuration_exported_policies']
    full_run = not tags or bool(set(tags) & {'all', 'tagged'})
    selected = set(tags)
    skipped = set(skip_tags or [])

    def add(action, target, **details):
        operations.append(dict(action=action, target=target, **details))

    def reconcile_policies(owner, kind):
        identity = {'kind': kind, 'name': owner['name']}
        attached = {name for name, owners in assignments.items() if identity in owners}
        desired = set(policy_names(owner, kind))
        for name in sorted(attached - desired):
            add('detach_policy', owner['name'], kind=kind, policy=name)
        for name in sorted(desired - attached):
            add('attach_policy', owner['name'], kind=kind, policy=name)

    if (full_run or 'backet' in selected) and 'backet' not in skipped:
        for bucket in buckets:
            name = bucket['name']
            actual = existing_buckets.get(name)
            if actual is None:
                add('create_bucket', name, versioning=to_bool(bucket.get('versioning', False)))
            elif actual['versioning'] != to_bool(bucket.get('versioning', False)):
                add('set_versioning', name, enabled=to_bool(bucket.get('versioning', False)))
            if 'anonymous' in bucket:
                preset = bucket['anonymous']
                # Snapshot documents identify private access; other presets are requested writes.
                already_private = (actual is None or actual.get('anonymous') == 'none')
                if preset not in ('none', 'private') or not already_private:
                    add('set_anonymous', name, preset=preset)
            if 'anonymous_policy' in bucket and (actual is None or actual.get('anonymous_policy') != bucket['anonymous_policy']):
                add('set_anonymous_policy', name, document=bucket['anonymous_policy'])

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
            actual_document = existing_policies.get(rule['name'])
            if actual_document != document:
                action = 'create_policy' if actual_document is None else 'update_policy'
                add(action, rule['name'], owner_type=rule['kind'], owner=rule['owner'], document=document)
        for group in groups:
            name = group['name']
            desired_members = set(group.get('members', []))
            desired_members.update(user['name'] for user in users if name in user.get('groups', []))
            if name not in existing_groups and not desired_members:
                raise AnsibleFilterError('mc cannot create an empty group: ' + name)
            new_group = name not in existing_groups
            actual_group = existing_groups.get(name, {'members': [], 'status': 'enabled'})
            if new_group:
                add('create_group', name, members=sorted(desired_members))
                existing_groups[name] = actual_group
            actual_members = set(actual_group['members'])
            for member in sorted(desired_members - actual_members):
                if not new_group:
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
                if group not in existing_groups:
                    add('create_group', group, members=[name])
                    existing_groups[group] = {'members': [name], 'status': 'enabled'}
                else:
                    add('add_group_member', group, user=name)
        for user in users:
            if 'status' in user and user['status'] != existing_users[user['name']]['status']:
                add('set_user_status', user['name'], status=user['status'])
        if users_delete:
            desired_users = {user['name'] for user in users}
            for name in sorted(set(existing_users) - desired_users - set(protected_users)):
                add('remove_user', name)
    return operations


def plan_summary(operations):
    """Group cluster mutations for console output and a controller-side YAML report."""
    categories = {
        'create_bucket': ('add', 'bucket'),
        'create_user': ('add', 'user'),
        'create_group': ('add', 'group'),
        'create_policy': ('add', 'policy'),
        'attach_policy': ('add', 'policy_assignment'),
        'add_group_member': ('add', 'group_member'),
        'set_versioning': ('change', 'bucket'),
        'set_anonymous': ('change', 'bucket'),
        'set_anonymous_policy': ('change', 'bucket'),
        'update_user_password': ('change', 'user'),
        'set_user_status': ('change', 'user'),
        'set_group_status': ('change', 'group'),
        'update_policy': ('change', 'policy'),
        'remove_user': ('delete', 'user'),
        'detach_policy': ('delete', 'policy_assignment'),
        'remove_group_member': ('delete', 'group_member'),
    }
    summary = {'add': [], 'change': [], 'delete': []}
    for operation in operations:
        category, kind = categories[operation['action']]
        entry = {'type': kind, 'name': operation['target'], 'action': operation['action']}
        entry.update({key: value for key, value in operation.items() if key not in ('target', 'action')})
        summary[category].append(entry)
    return summary


def plan_console(summary):
    """Keep the console summary compact without changing the complete YAML report."""
    return {
        category: [{key: value for key, value in entry.items() if key != 'document'}
                   for entry in entries]
        for category, entries in summary.items()
    }


class FilterModule:
    def filters(self):
        return {'minio_configuration_policy_definitions': policy_definitions,
                'minio_configuration_policy_names': policy_names,
                'minio_configuration_plan': configuration_plan,
                'minio_configuration_plan_summary': plan_summary,
                'minio_configuration_plan_console': plan_console}
