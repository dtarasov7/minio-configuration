#!/usr/bin/env python3
"""Fixture allowing only policy reads and recording policy attachment changes."""
import json
from pathlib import Path
import sys

arguments = sys.argv[1:]
if arguments[:5] == ['--json', 'admin', 'user', 'info', 'production'] and arguments[5] in ['reader', 'reader2']:
    print(json.dumps({'status': 'success', 'policyName': 'read,old-policy'}))
elif arguments[:4] in (['admin', 'policy', 'attach', 'production'], ['admin', 'policy', 'detach', 'production']):
    output = Path(__file__).resolve().parents[3] / '.ansible' / 'reconcile-commands.jsonl'
    with output.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(arguments) + '\n')
    print('{}')
else:
    raise SystemExit('Unexpected mc operation: ' + repr(arguments))
