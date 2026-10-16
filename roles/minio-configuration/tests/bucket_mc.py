#!/usr/bin/env python3
"""Record bucket commands and reject destructive operations."""
import json
from pathlib import Path
import sys


arguments = sys.argv[1:]
log_path = Path(__file__).resolve().parents[3] / '.ansible/bucket-commands.jsonl'
with log_path.open('a', encoding='utf-8') as log:
    log.write(json.dumps(arguments) + '\n')

allowed = [
    ['mb', '--ignore-existing', 'production/public'],
    ['mb', '--ignore-existing', 'production/private'],
    ['version', 'suspend', 'production/public'],
    ['version', 'enable', 'production/private'],
]
if arguments not in allowed:
    sys.exit('Unexpected or destructive command: ' + repr(arguments))
