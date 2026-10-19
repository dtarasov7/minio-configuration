"""Conservative access matrix for direct built-in IAM and anonymous policies."""
import csv
import io
import json
import re

from ansible.errors import AnsibleFilterError


ACTIONS = [('s3:ListBucket', 'L', 'bucket'), ('s3:GetObject', 'R', 'objects'),
           ('s3:PutObject', 'W', 'objects'), ('s3:DeleteObject', 'D', 'objects')]
ARN = 'arn:aws:s3:::'


def string_list(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return value
    raise ValueError('Expected a string or a nonempty list of strings')


def statements(document):
    rules = document['Statement']
    if isinstance(rules, dict):
        rules = [rules]
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ValueError('Statement must be an object or a list of objects')
    return rules


def resource_area(resource):
    """Return (bucket, scope, key) for the supported resource language."""
    if resource in ('*', ARN + '*'):
        return ('*', '*', '*')
    if not resource.startswith(ARN):
        return None
    bucket, separator, key = resource[len(ARN):].partition('/')
    if not bucket or any(character in bucket for character in '*?${}'):
        return None
    if not separator:
        return (bucket, 'bucket', '')
    if not key or any(character in key for character in '?${}'):
        return None
    if '*' in key and not (key.endswith('/*') and key.count('*') == 1) and key != '*':
        return None
    return (bucket, 'objects', key)


def overlap(area, row):
    """Return full, partial or no coverage of a row by a supported resource."""
    bucket, scope, key = area
    if bucket == '*':
        return 'full'
    if bucket != row[0] or scope != row[1]:
        return None
    row_key = row[2]
    if key == row_key or scope == 'bucket':
        return 'full'
    if key.endswith('*') and row_key.startswith(key[:-1]):
        return 'full'
    if row_key.endswith('*') and key.startswith(row_key[:-1]):
        return 'partial'
    return None


def compile_rule(statement, anonymous):
    reasons = []
    if 'Condition' in statement:
        reasons.append('Condition is not evaluated')
    if 'NotAction' in statement or 'NotResource' in statement:
        reasons.append('NotAction/NotResource is not supported')
    allowed = {'Sid', 'Effect', 'Action', 'Resource', 'Condition'}
    if anonymous:
        allowed.add('Principal')
        principal = statement.get('Principal')
        public = principal == '*' or principal == {'AWS': '*'} or principal == {'AWS': ['*']}
        if not public or 'NotPrincipal' in statement:
            reasons.append('Principal/NotPrincipal is not supported')
    if set(statement) - allowed:
        reasons.append('Unsupported statement fields: ' + ', '.join(sorted(set(statement) - allowed)))
    effect = statement.get('Effect')
    if effect not in ('Allow', 'Deny'):
        reasons.append('Unknown Effect')
    patterns = string_list(statement['Action']) if 'Action' in statement else ['*']
    if 'Action' not in statement:
        reasons.append('Action is missing')
    if 'NotAction' in statement:
        patterns = ['*']
    actions = {action for action, _, _ in ACTIONS
               if any(re.fullmatch(re.escape(pattern.lower()).replace(r'\*', '.*').replace(r'\?', '.'),
                                   action.lower()) for pattern in patterns)}
    known_actions = {action.lower() for action, _, _ in ACTIONS}
    outside_actions = any(pattern.lower() not in known_actions for pattern in patterns)
    resources = string_list(statement['Resource']) if 'Resource' in statement else ['*']
    areas = [resource_area(resource) for resource in resources]
    unknown_resource = 'Resource' not in statement or 'NotResource' in statement or None in areas
    if unknown_resource:
        reasons.append('Resource/NotResource is missing or unsupported')
    uncertain = bool(reasons)
    # Broad action masks are supported within the four-action model.
    if outside_actions:
        reasons.append('Actions outside L/R/W/D are not reported (action masks cover only L/R/W/D)')
    return {'actions': actions, 'effect': effect, 'areas': [area for area in areas if area],
            'unknown_resource': unknown_resource, 'uncertain': uncertain, 'reasons': reasons}


def cell_value(rules, row):
    values = []
    for action, label, scope in ACTIONS:
        if row[1] != scope:
            continue
        allow = deny = uncertain = partial_allow = partial_deny = False
        for rule in rules:
            if action not in rule['actions']:
                continue
            if rule['bucket_limit'] is not None and rule['bucket_limit'] != row[0]:
                continue
            coverage = [overlap(area, row) for area in rule['areas']]
            applies = 'full' in coverage
            partial = 'partial' in coverage
            if rule['unknown_resource'] or (rule['uncertain'] and (applies or partial)):
                uncertain = True
            elif applies:
                allow = allow or rule['effect'] == 'Allow'
                deny = deny or rule['effect'] == 'Deny'
            elif partial:
                partial_allow = partial_allow or rule['effect'] == 'Allow'
                partial_deny = partial_deny or rule['effect'] == 'Deny'
        if deny:
            values.append('!' + label)
        elif uncertain or partial_deny or (partial_allow and not allow):
            values.append(label + '?')
        elif allow:
            values.append(label)
    return ' '.join(values) or '—'


def matrix_report(snapshot):
    users = sorted(snapshot['users'], key=lambda user: user['name'])
    buckets = sorted(snapshot['buckets'], key=lambda bucket: bucket['name'])
    names = {bucket['name'] for bucket in buckets}
    rows = {(name, scope, key) for name in names
            for scope, key in [('bucket', ''), ('objects', '*')]}
    rules_by_subject = {'anonymous': []}
    notes = []

    def add_document(subject, policy, document, bucket_limit=None):
        for index, statement in enumerate(statements(document), 1):
            rule = compile_rule(statement, subject == 'anonymous')
            rule['bucket_limit'] = bucket_limit
            rules_by_subject[subject].append(rule)
            for area in rule['areas']:
                if area[0] in names and (bucket_limit is None or area[0] == bucket_limit):
                    rows.add(area)
            if rule['reasons']:
                identity = {'subject': subject, 'policy': policy,
                            'statement': index, 'Sid': statement.get('Sid'), 'reasons': rule['reasons']}
                notes.append(json.dumps(identity, ensure_ascii=False, sort_keys=True))

    for bucket in buckets:
        add_document('anonymous', 'bucket:' + bucket['name'], bucket['policy'], bucket['name'])
    for user in users:
        subject = 'user:' + user['name']
        rules_by_subject[subject] = []
        for name in sorted(user['policies']):
            add_document(subject, name, snapshot['policies'][name])

    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['bucket', 'scope', 'resource', 'anonymous'] + ['user:' + user['name'] for user in users])
    for row in sorted(rows):
        resource = row[0] + ('/' + row[2] if row[1] == 'objects' else '')
        cells = [cell_value(rules_by_subject['anonymous'], row)]
        for user in users:
            value = ('DISABLED' if user['status'] == 'disabled'
                     else cell_value(rules_by_subject['user:' + user['name']], row))
            cells.append(value)
        writer.writerow(list(row[:2]) + [resource] + cells)

    explanation = [
        'Матрица прямых прав / Direct access matrix (source: cluster)',
        'Alias: ' + json.dumps(snapshot['alias'], ensure_ascii=False),
        'UTC: {} — {}'.format(snapshot['started_at'], snapshot['finished_at']),
        'L=ListBucket; R=GetObject; W=PutObject; D=DeleteObject; !R=explicit Deny (likewise L/W/D).',
        '— = no Allow in supported rules; R? = unknown/mixed decision for R (likewise L/W/D).',
        'DISABLED = disabled user. A broad resource row may contain exceptions shown in narrower rows.',
        'Only direct built-in user policies and anonymous bucket policies are evaluated.',
        'Groups and bucket-policy effects on authenticated users are excluded.',
        'Root, service accounts, STS, LDAP/OIDC and external authorization are excluded.',
        'Conditions are not evaluated; affected decisions are marked ?. No object listing is performed.',
        'This is a limited policy model, not a complete effective-access audit or an apply forecast.',
        'Reads are not atomic: concurrent cluster changes may affect the result.',
        'Skipped/limited rules: {}'.format(len(notes)),
    ]
    explanation.extend(notes)
    return {'csv': stream.getvalue(), 'notes': '\n'.join(explanation) + '\n',
            'row_count': len(rows), 'user_count': len(users), 'warning_count': len(notes)}


def access_matrix(snapshot):
    try:
        return matrix_report(snapshot)
    except (ValueError, KeyError, TypeError) as error:
        raise AnsibleFilterError('Cannot build MinIO access matrix: {}'.format(error)) from error


class FilterModule:
    def filters(self):
        return {'minio_configuration_access_matrix': access_matrix}
