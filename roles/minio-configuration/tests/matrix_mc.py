#!/usr/bin/env python3
"""Matrix fixture: every unexpected (including mutating) command fails."""
import json
from pathlib import Path
import sys

arguments = sys.argv[1:]
if arguments == ['admin', 'info', 'production']:
    print('{}')
    sys.exit(0)

rule = {'Sid': 'Read', 'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': 'arn:aws:s3:::data/*'}
responses = {
    ('ls', 'production'): [{'key': 'data/'}],
    ('anonymous', 'get-json', 'production/data'): [{'anonymous': {'Statement': [dict(rule, Principal={'AWS': ['*']})]}}],
    ('admin', 'user', 'list', 'production'): [
        {'accessKey': 'reader', 'userStatus': 'enabled', 'policyName': 'read', 'memberOf': [{'name': 'staff', 'policies': ['group-deny']}]},
        {'accessKey': 'group-only', 'userStatus': 'enabled', 'memberOf': [{'name': 'staff', 'policies': ['group-read']}]},
        {'accessKey': 'off', 'userStatus': 'disabled', 'policyName': 'read'}],
    ('admin', 'policy', 'info', 'production', 'read'): [{'policyInfo': {'policy': {'Statement': [rule]}}}],
}
if not arguments or arguments[0] != '--json':
    sys.exit('Expected --json read')
key = tuple(arguments[1:])
if key not in responses:
    sys.exit('Unexpected command: ' + repr(key))
log = Path(__file__).resolve().parents[3] / '.ansible/matrix-commands.jsonl'
with log.open('a') as stream:
    stream.write(json.dumps(arguments) + '\n')
for record in responses[key]:
    print(json.dumps(record, indent=2))
