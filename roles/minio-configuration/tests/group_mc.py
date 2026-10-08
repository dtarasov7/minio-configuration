#!/usr/bin/env python3
"""Stateful fixture for group creation and exact managed-user membership tests."""
import json
from pathlib import Path
import sys

state_path = Path(__file__).resolve().parents[3] / '.ansible' / 'group-state.json'
state = json.loads(state_path.read_text())
arguments = sys.argv[1:]
read_only = arguments[:1] == ['--json']
if read_only:
    arguments = arguments[1:]
if len(arguments) < 4 or arguments[0] != 'admin' or arguments[3] != 'production':
    raise SystemExit('Unexpected command or alias: ' + repr(arguments))
entity, operation = arguments[1:3]
if read_only and entity == 'user' and operation == 'info':
    name = arguments[4]
    memberships = [{'name': group} for group, info in state['groups'].items() if name in info['members']]
    response = {'status': 'success', 'memberOf': memberships}
elif read_only and entity == 'group' and operation == 'info':
    info = state['groups'][arguments[4]]
    response = {'status': 'success', 'members': info['members'],
                'groupPolicy': ','.join(info['policies']), 'groupStatus': info['status']}
elif not read_only and entity == 'group':
    name = arguments[4]
    if operation == 'add':
        info = state['groups'].setdefault(name, {'members': [], 'policies': [], 'status': 'enabled'})
        info['members'] = sorted(set(info['members']) | set(arguments[5:]))
    elif operation == 'remove':
        # Removing the last member must retain an existing empty group.
        info = state['groups'][name]
        info['members'] = sorted(set(info['members']) - set(arguments[5:]))
    elif operation in ('enable', 'disable'):
        state['groups'][name]['status'] = 'enabled' if operation == 'enable' else 'disabled'
    else:
        raise SystemExit('Unexpected group operation: ' + operation)
    response = {}
elif not read_only and entity == 'policy' and operation in ('attach', 'detach') and arguments[5] == '--group':
    info = state['groups'][arguments[6]]
    policy = arguments[4]
    if operation == 'attach':
        info['policies'] = sorted(set(info['policies']) | {policy})
    else:
        info['policies'] = sorted(set(info['policies']) - {policy})
    response = {}
else:
    raise SystemExit('Unexpected operation: ' + repr(arguments))
if not read_only:
    state['commands'].append(arguments)
    state_path.write_text(json.dumps(state))
print(json.dumps(response))
