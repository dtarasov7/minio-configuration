#!/usr/bin/env python3
"""Stateful IAM fixture; reject deletion of policies with surviving assignments."""
import json
from pathlib import Path
import sys


state_path = Path(__file__).resolve().parents[3] / '.ansible/policy-remove-state.json'
state = json.loads(state_path.read_text())
arguments = [argument for argument in sys.argv[1:] if argument != '--json']
response = {}
if arguments == ['admin', 'info', 'production']:
    pass
elif arguments == ['ls', 'production']:
    response = []
elif len(arguments) >= 4 and arguments[0] == 'admin' and arguments[3] == 'production':
    entity, operation = arguments[1:3]
    name = arguments[4] if len(arguments) > 4 else None
    if entity == 'user' and operation == 'list':
        response = [{'accessKey': user} for user in sorted(state['users'])]
    elif entity == 'user' and operation == 'info':
        user = state['users'][name]
        response = {'userStatus': 'enabled', 'policyName': ','.join(user['policies']), 'memberOf': []}
    elif entity == 'group' and operation == 'list':
        response = {'groups': sorted(state['groups'])}
    elif entity == 'group' and operation == 'info':
        group = state['groups'][name]
        response = {'groupStatus': 'enabled', 'groupPolicy': ','.join(group['policies']), 'members': []}
    elif entity == 'policy' and operation == 'list':
        response = [{'policy': policy} for policy in sorted(state['policies'])]
    elif entity == 'policy' and operation == 'info':
        response = {'policyInfo': {'policy': state['policies'][name]}}
    elif entity in ('user', 'policy') and operation == 'remove':
        if state['read_only']:
            raise SystemExit('Writes are forbidden during dry mode')
        if entity == 'user':
            del state['users'][name]
        else:
            owners = list(state['users'].values()) + list(state['groups'].values())
            if any(name in owner['policies'] for owner in owners):
                raise SystemExit('Policy is still assigned')
            del state['policies'][name]
        state['commands'].append(arguments)
        state_path.write_text(json.dumps(state))
    else:
        raise SystemExit('Unexpected command: ' + repr(arguments))
else:
    raise SystemExit('Unexpected command: ' + repr(arguments))

records = response if isinstance(response, list) else [response]
for record in records:
    print(json.dumps(record))
