"""Build owner-specific, per-statement MinIO policy definitions."""
import re

from ansible.errors import AnsibleFilterError


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


class FilterModule:
    def filters(self):
        return {'minio_configuration_policy_definitions': policy_definitions,
                'minio_configuration_policy_names': policy_names}
