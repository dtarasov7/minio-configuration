#!/usr/bin/env python3
"""Stateful CLI fixture for testing the lab verification script itself."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[:1] == ['--config-dir']:
    args = args[2:]
if args[:1] == ['--json']:
    args = args[1:]
state_path = Path(os.environ['LAB_CLIENT_STATE'])
state = json.loads(state_path.read_text())
state['calls'].append(args)


def finish(code=0, message=''):
    state_path.write_text(json.dumps(state))
    if message:
        print(message)
    sys.exit(code)


if args[:2] in (['admin', 'info'], ['alias', 'set']):
    finish()
operation = args[0]
target = args[-1]
alias, key = target.split('/', 1)
restricted = alias == 'test'
inside = key.startswith('lab-other/other/')
denied = restricted and not inside and operation in ('ls', 'cp', 'rm')
if denied:
    mode = os.environ.get('LAB_CLIENT_FAILURE', '')
    if mode == 'network':
        finish(1, 'connection refused')
    if mode != 'allow':
        finish(1, '{"status":"error","error":{"Code":"AccessDenied"}}')
if operation == 'cp':
    state['objects'][key] = Path(args[1]).read_text()
elif operation == 'cat':
    if key not in state['objects']:
        finish(1, 'NoSuchKey')
    print(state['objects'][key], end='')
elif operation == 'rm':
    state['objects'].pop(key, None)
elif operation == 'stat':
    if key not in state['objects']:
        finish(1, 'NoSuchKey')
elif operation == 'ls':
    for name in state['objects']:
        if name.startswith(key):
            print(json.dumps({'key': name[len(key):]}))
else:
    finish(1, 'Unexpected operation')
finish()
