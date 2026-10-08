#!/usr/bin/python
"""Read bucket policies and built-in IAM configuration through mc, without writes."""
import copy
import hashlib
import json
import re

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r'''
---
module: minio_configuration_snapshot
short_description: Read MinIO bucket and IAM configuration using mc
description: Collect a reusable desired state without changing the MinIO server.
options:
  binary:
    description: Path to the installed MinIO client.
    type: path
    required: true
  alias:
    description: Existing authenticated mc alias.
    type: str
    default: local
  operation:
    description: Export desired state or read direct policy ownership assignments.
    type: str
    choices: [snapshot, assignments]
    default: snapshot
attributes:
  check_mode:
    support: full
'''


def decode_stream(output):
    """Accept compact JSONL as well as consecutive pretty-printed JSON objects."""
    decoder = json.JSONDecoder()
    remaining = output.strip()
    records = []
    while remaining:
        record, end = decoder.raw_decode(remaining)
        if not isinstance(record, dict):
            raise ValueError('Expected an object in mc JSON output')
        records.append(record)
        remaining = remaining[end:].lstrip()
    return records


def policy_document(response):
    info = response.get('policyInfo', response)
    document = info.get('Policy', info.get('policy', info))
    if isinstance(document, str):
        document = json.loads(document)
    if not isinstance(document, dict) or 'Statement' not in document:
        raise ValueError('mc returned no IAM policy document')
    return document


def policy_names(value):
    return sorted({name.strip() for name in value.split(',') if name.strip()})


def owner_statements(policy_names, documents):
    statements = []
    seen_sids = set()
    for name in policy_names:
        document_statements = documents[name]['Statement']
        if isinstance(document_statements, dict):
            document_statements = [document_statements]
        if not isinstance(document_statements, list):
            raise ValueError('Policy Statement must be a list or object: ' + name)
        for index, original in enumerate(document_statements):
            if not isinstance(original, dict):
                raise ValueError('Policy statement must be an object: ' + name)
            statement = copy.deepcopy(original)
            sid = statement.get('Sid')
            if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9]+', sid) or sid in seen_sids:
                identity = json.dumps([name, index, original], sort_keys=True, ensure_ascii=False)
                suffix = hashlib.sha256(identity.encode('utf-8')).hexdigest()
                sid = 'Export' + suffix
                while sid in seen_sids:
                    sid += 'X'
            seen_sids.add(sid)
            statement['Sid'] = sid
            statements.append(statement)
    return statements


class Snapshot:
    def __init__(self, module):
        self.module = module
        self.binary = module.params['binary']
        self.alias = module.params['alias']

    def read(self, *arguments):
        command = [self.binary, '--json'] + list(arguments)
        returncode, stdout, stderr = self.module.run_command(command)
        if returncode:
            raise ValueError('mc failed for {}: {}'.format(' '.join(arguments), stderr or stdout))
        records = decode_stream(stdout)
        for record in records:
            if record.get('status') == 'error':
                raise ValueError('mc reported an error: {}'.format(record))
        return records

    def one(self, *arguments):
        records = self.read(*arguments)
        if len(records) != 1:
            raise ValueError('Expected one mc response for {}'.format(arguments))
        return records[0]

    def collect(self):
        buckets = []
        users = []
        groups = []
        names = set()
        bucket_records = self.read('ls', self.alias)
        for record in sorted(bucket_records, key=lambda entry: entry['key']):
            name = record['key'].rstrip('/')
            target = self.alias + '/' + name
            anonymous = self.one('anonymous', 'get-json', target)
            version = self.one('version', 'info', target)
            bucket = {'name': name, 'versioning': version['versioning']['status'] == 'Enabled'}
            document = anonymous.get('anonymous')
            if document and document.get('Statement'):
                bucket['anonymous_policy'] = document
            elif anonymous.get('permission') in ('private', 'none'):
                bucket['anonymous'] = 'none'
            else:
                raise ValueError('Missing anonymous policy for bucket ' + name)
            buckets.append(bucket)

        user_records = self.read('admin', 'user', 'list', self.alias)
        for record in sorted(user_records, key=lambda entry: entry['accessKey']):
            name = record['accessKey']
            info = self.one('admin', 'user', 'info', self.alias, name)
            policies = policy_names(info.get('policyName', ''))
            names.update(policies)
            status = info['userStatus']
            if status not in ('enabled', 'disabled'):
                raise ValueError('Unknown user status: ' + status)
            memberships = sorted(group['name'] for group in info.get('memberOf', []))
            users.append({'name': name, 'status': status, 'policies': policies, 'groups': memberships})

        group_list = self.one('admin', 'group', 'list', self.alias)
        for name in sorted(group_list.get('groups', [])):
            info = self.one('admin', 'group', 'info', self.alias, name)
            policies = policy_names(info.get('groupPolicy', ''))
            names.update(policies)
            status = info['groupStatus']
            if status not in ('enabled', 'disabled'):
                raise ValueError('Unknown group status: ' + status)
            groups.append({'name': name, 'members': sorted(info.get('members', [])),
                           'status': status, 'policies': policies})

        documents = {}
        for name in sorted(names):
            response = self.one('admin', 'policy', 'info', self.alias, name)
            documents[name] = policy_document(response)
        for owner in users + groups:
            attached_names = owner.pop('policies')
            owner['statements'] = owner_statements(attached_names, documents)
        return {'minio_configuration_backets': buckets,
                'minio_configuration_users': users,
                'minio_configuration_groups': groups,
                'minio_configuration_backets_delete': False,
                'minio_configuration_users_delete': False,
                'minio_configuration_mode': 'apply'}

    def collect_assignments(self):
        assignments = {}
        users = self.read('admin', 'user', 'list', self.alias)
        for record in users:
            name = record['accessKey']
            info = self.one('admin', 'user', 'info', self.alias, name)
            for policy in policy_names(info.get('policyName', '')):
                assignments.setdefault(policy, []).append({'kind': 'user', 'name': name})
        groups = self.one('admin', 'group', 'list', self.alias)
        for name in groups.get('groups', []):
            info = self.one('admin', 'group', 'info', self.alias, name)
            for policy in policy_names(info.get('groupPolicy', '')):
                assignments.setdefault(policy, []).append({'kind': 'grp', 'name': name})
        return assignments


def main():
    module = AnsibleModule(argument_spec={'binary': {'type': 'path', 'required': True},
                                         'alias': {'type': 'str', 'default': 'local'},
                                         'operation': {'type': 'str', 'choices': ['snapshot', 'assignments'], 'default': 'snapshot'}},
                           supports_check_mode=True)
    snapshot = Snapshot(module)
    try:
        if module.params['operation'] == 'assignments':
            assignments = snapshot.collect_assignments()
            module.exit_json(changed=False, assignments=assignments)
        configuration = snapshot.collect()
    except (ValueError, KeyError, TypeError) as error:
        module.fail_json(msg='Cannot read MinIO configuration: {}'.format(error))
    module.exit_json(changed=False, configuration=configuration)


if __name__ == '__main__':
    main()
