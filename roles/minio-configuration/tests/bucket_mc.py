#!/usr/bin/env python3
"""Model versioning states and reject destructive or unnecessary suspension commands."""
import json
from pathlib import Path
import sys


arguments = sys.argv[1:]
log_path = Path(__file__).resolve().parents[3] / '.ansible/bucket-commands.jsonl'
with log_path.open('a', encoding='utf-8') as log:
    log.write(json.dumps(arguments) + '\n')

state_path = log_path.parent / 'bucket-state.json'
state = json.loads(state_path.read_text())
command = [argument for argument in arguments if argument != '--json']
if command == ['ls', 'production']:
    for name in sorted(state):
        print(json.dumps({'key': name + '/'}, indent=2))
    sys.exit(0)
if len(command) != 3 or not command[2].startswith('production/'):
    sys.exit('Unexpected or destructive command: ' + repr(arguments))
name = command[2].split('/', 1)[1]
if command[:2] == ['mb', '--ignore-existing']:
    state.setdefault(name, '')
elif command[:2] == ['version', 'info']:
    print(json.dumps({'versioning': {'status': state[name]}}, indent=2))
    sys.exit(0)
elif command[:2] == ['version', 'enable']:
    state[name] = 'Enabled'
elif command[:2] == ['version', 'suspend']:
    if state[name] != 'Enabled':
        sys.exit('Only enabled buckets should be suspended')
    state[name] = 'Suspended'
else:
    sys.exit('Unexpected or destructive command: ' + repr(arguments))
state_path.write_text(json.dumps(state))
