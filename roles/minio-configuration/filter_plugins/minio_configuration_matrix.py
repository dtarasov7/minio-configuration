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
    if '*' in key and not (key.endswith('*') and key.count('*') == 1):
        return None
    return (bucket, 'objects', key)


def resource_scope(resource):
    """Keep an unsupported object's uncertainty inside its identifiable bucket."""
    if resource.startswith(ARN):
        bucket, separator, _ = resource[len(ARN):].partition('/')
        if bucket and not any(character in bucket for character in '${}'):
            scope = 'objects' if separator else ('*' if '*' in bucket or '?' in bucket else 'bucket')
            return (bucket, scope, '*')
    return ('*', '*', '*')


def wildcard_matches(pattern, value):
    expression = re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')
    return re.fullmatch(expression, value) is not None


def overlap(area, row):
    """Return full, partial or no coverage of a row by a supported resource."""
    bucket, scope, key = area
    if bucket == '*' and scope == '*':
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


def prefix_conditions(condition):
    """Parse positive prefix comparisons; None keeps other conditions unknown."""
    if not isinstance(condition, dict) or not condition:
        return None
    comparisons = []
    for operator, entries in condition.items():
        if operator not in ('StringLike', 'StringEquals') or not isinstance(entries, dict):
            return None
        if set(entries) != {'s3:prefix'}:
            return None
        patterns = string_list(entries['s3:prefix'])
        for pattern in patterns:
            if any(character in pattern for character in '?${}'):
                return None
            if '*' in pattern and (operator == 'StringEquals' or not pattern.endswith('*') or pattern.count('*') != 1):
                return None
        comparisons.append(patterns)
    return comparisons


def prefix_coverage(comparisons, row):
    """Compare prefix-request ranges; operators combine with AND, values with OR."""
    patterns = comparisons[0] if comparisons else ['*']
    for candidates in comparisons[1:]:
        intersections = set()
        for left in patterns:
            for right in candidates:
                left_area = (row[0], 'objects', left)
                right_area = (row[0], 'objects', right)
                if overlap(left_area, right_area) == 'full':
                    intersections.add(right)
                elif overlap(right_area, left_area) == 'full':
                    intersections.add(left)
        patterns = sorted(intersections)
    coverage = [overlap((row[0], 'objects', pattern), row) for pattern in patterns]
    if 'full' in coverage:
        return 'full'
    return 'partial' if 'partial' in coverage else None


def compile_rule(statement, anonymous):
    reasons = []
    comparisons = []
    if 'Condition' in statement:
        comparisons = prefix_conditions(statement['Condition'])
        if comparisons is None:
            reasons.append('Condition is not evaluated: only StringLike/StringEquals s3:prefix is supported')
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
               if any(wildcard_matches(pattern.lower(), action.lower()) for pattern in patterns)}
    known_actions = {action.lower() for action, _, _ in ACTIONS}
    outside_actions = any(pattern.lower() not in known_actions for pattern in patterns)
    uncertain = bool(reasons)
    resources = string_list(statement['Resource']) if 'Resource' in statement else ['*']
    areas = [resource_area(resource) for resource in resources]
    unknown_areas = [resource_scope(resource) for resource, area in zip(resources, areas) if area is None]
    if 'Resource' not in statement or 'NotResource' in statement:
        unknown_areas = [('*', '*', '*')]
    if unknown_areas:
        reasons.append('Resource/NotResource is missing or unsupported')
    # Broad action masks are supported within the four-action model.
    if outside_actions:
        reasons.append('Actions outside L/R/W/D are not reported (action masks cover only L/R/W/D)')
    if comparisons and actions - {'s3:ListBucket'}:
        reasons.append('s3:prefix is evaluated only for ListBucket; other actions remain uncertain')
    return {'actions': actions, 'effect': effect, 'areas': [area for area in areas if area],
            'unknown_areas': unknown_areas, 'uncertain': uncertain, 'reasons': reasons,
            'prefix_conditions': comparisons}


def direct_rule(rule, row, scope):
    """Distinguish the row's own resource range from a broader matching rule."""
    if scope == 'objects':
        return row in rule['areas'] or (
            rule['bucket_limit'] == row[0] and row[2] == '*' and ('*', '*', '*') in rule['areas'])
    bucket_direct = (row[0], 'bucket', '') in rule['areas'] or (
        rule['bucket_limit'] == row[0] and ('*', '*', '*') in rule['areas'])
    comparisons = rule['prefix_conditions']
    if comparisons:
        return bucket_direct and any(row[2] in patterns for patterns in comparisons)
    return bucket_direct and row[2] == '*'


def cell_value(rules, row):
    values = []
    for action, label, scope in ACTIONS:
        # ListBucket still applies to the bucket ARN; only its display moves to
        # the object row. An object ARN with Action '*' never grants ListBucket.
        target = (row[0], 'bucket', '') if scope == 'bucket' else row
        allow = deny = uncertain = False
        direct_allow = direct_deny = False
        for rule in rules:
            if action not in rule['actions']:
                continue
            if rule['bucket_limit'] is not None and rule['bucket_limit'] != row[0]:
                continue
            coverage = [overlap(area, target) for area in rule['areas']]
            applies = 'full' in coverage
            comparisons = rule['prefix_conditions']
            if comparisons and action == 's3:ListBucket':
                condition_coverage = prefix_coverage(comparisons, row)
                if condition_coverage != 'full':
                    continue
            unknown_resource = any(wildcard_matches(area[0], target[0]) and area[1] in ('*', target[1])
                                   for area in rule['unknown_areas'])
            unknown_condition = rule['uncertain'] or (bool(comparisons) and action != 's3:ListBucket')
            if unknown_resource or (unknown_condition and applies):
                uncertain = True
            elif applies:
                allow = allow or rule['effect'] == 'Allow'
                deny = deny or rule['effect'] == 'Deny'
                direct = direct_rule(rule, row, scope)
                direct_allow = direct_allow or (rule['effect'] == 'Allow' and direct)
                direct_deny = direct_deny or (rule['effect'] == 'Deny' and direct)
        if deny:
            values.append('!' + (label if direct_deny else label.lower()))
        elif uncertain:
            values.append('?')
        elif allow:
            values.append(label if direct_allow else label.lower())
        else:
            values.append('-')
    return ' '.join(value.ljust(2) for value in values).rstrip()


def matrix_report(snapshot):
    users = sorted(snapshot['users'], key=lambda user: user['name'])
    buckets = sorted(snapshot['buckets'], key=lambda bucket: bucket['name'])
    names = {bucket['name'] for bucket in buckets}
    rows = {(name, 'objects', '*') for name in names}
    rules_by_subject = {'anonymous': []}
    notes = []

    def add_document(subject, policy, document, bucket_limit=None):
        for index, statement in enumerate(statements(document), 1):
            rule = compile_rule(statement, subject == 'anonymous')
            rule['bucket_limit'] = bucket_limit
            rules_by_subject[subject].append(rule)
            for area in rule['areas']:
                if area[0] in names and area[1] == 'objects' and (bucket_limit is None or area[0] == bucket_limit):
                    rows.add(area)
                if area[1] in ('bucket', '*') and 's3:ListBucket' in rule['actions']:
                    for name in sorted(names):
                        if area[0] not in ('*', name) or bucket_limit not in (None, name):
                            continue
                        for patterns in rule['prefix_conditions'] or []:
                            rows.update((name, 'objects', pattern) for pattern in patterns)
            if rule['reasons']:
                identity = {'subject': subject, 'policy': policy,
                            'statement': index, 'Sid': statement.get('Sid'), 'reasons': rule['reasons']}
                for field in ('Action', 'NotAction', 'Resource', 'NotResource', 'Condition'):
                    if field in statement:
                        identity[field] = statement[field]
                notes.append(json.dumps(identity, ensure_ascii=False, sort_keys=True))

    for bucket in buckets:
        add_document('anonymous', 'bucket:' + bucket['name'], bucket['policy'], bucket['name'])
    for user in users:
        subject = 'u:' + user['name']
        rules_by_subject[subject] = []
        for name in sorted(user['policies']):
            add_document(subject, name, snapshot['policies'][name])

    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';', lineterminator='\n')
    writer.writerow(['bucket', 'scope', 'resource', 'anonymous'] + ['u:' + user['name'] for user in users])
    for row in sorted(rows):
        resource = row[0] + ('/' + row[2] if row[1] == 'objects' else '')
        cells = [cell_value(rules_by_subject['anonymous'], row)]
        for user in users:
            value = ('DISABLED' if user['status'] == 'disabled'
                     else cell_value(rules_by_subject['u:' + user['name']], row))
            cells.append(value)
        writer.writerow(list(row[:2]) + [resource] + cells)

    explanation = [
        'Матрица прямых прав / Direct access matrix (source: cluster)',
        'Alias: ' + json.dumps(snapshot['alias'], ensure_ascii=False),
        'UTC: {} — {}'.format(snapshot['started_at'], snapshot['finished_at']),
        'L=ListBucket; R=GetObject; W=PutObject; D=DeleteObject; !R=explicit Deny (likewise L/W/D).',
        'Uppercase = a rule for this row; lowercase = a broader matching rule (also for !r/!w/!d/!l).',
        'CSV delimiter: semicolon. User columns: u:<name>. Fixed slots: L R W D (two characters each).',
        '- = no Allow covering this row; ? = calculation unknown in that fixed L/R/W/D slot.',
        'L is shown on object rows, but is evaluated against the bucket ARN, not an object ARN.',
        'DISABLED = disabled user. Narrower grants/denials appear in their own rows, without markers on broader rows.',
        'Each row shows covering rules; check narrower rows for overrides before judging access to a specific object.',
        'Only direct built-in user policies and anonymous bucket policies are evaluated.',
        'Groups and bucket-policy effects on authenticated users are excluded.',
        'Root, service accounts, STS, LDAP/OIDC and external authorization are excluded.',
        'ListBucket supports StringLike/StringEquals on s3:prefix (literal values or a trailing * for StringLike).',
        'L on a row describes prefix requests in that range; an exact prefix comparison does not cover every deeper request.',
        'Other conditions remain unknown (?). No object listing is performed.',
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
