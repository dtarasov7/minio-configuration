#!/usr/bin/env python3
"""Read-only fixture exposing direct policy assignments for ownership checks."""
import json
from pathlib import Path
import sys

state_path = Path(__file__).resolve().parents[3] / '.ansible' / 'guard-state.json'
assignments = json.loads(state_path.read_text())
arguments = sys.argv[1:]
if arguments[:1] != ['--json'] or len(arguments) < 5 or arguments[4] != 'production':
    raise SystemExit('Only read-only commands on production are allowed')
entity, operation = arguments[2:4]
kind = 'user' if entity == 'user' else 'grp'
names = sorted({owner['name'] for owners in assignments.values() for owner in owners if owner['kind'] == kind})
if entity == 'user' and operation == 'list':
    for name in names:
        print(json.dumps({'status': 'success', 'accessKey': name}))
    sys.exit(0)
if entity == 'group' and operation == 'list':
    response = {'status': 'success', 'groups': names}
elif operation == 'info':
    name = arguments[5]
    policies = [policy for policy, owners in assignments.items() if {'kind': kind, 'name': name} in owners]
    field = 'policyName' if entity == 'user' else 'groupPolicy'
    response = {'status': 'success', field: ','.join(policies)}
else:
    raise SystemExit('Unexpected operation')
print(json.dumps(response))
