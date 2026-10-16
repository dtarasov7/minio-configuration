#!/usr/bin/env python3
"""Read-only mc fixture for the local Ansible export integration test."""
import json
import sys
from test_snapshot import FakeModule, SNAPSHOT

if sys.argv[1:3] == ['admin', 'info']:
    if sys.argv[3:] != ['production']:
        sys.exit('Alias is not configured or accessible')
    print('{}')
    sys.exit(0)

module = FakeModule()
module.params = {'binary': '/mc', 'alias': 'production'}
module.responses = {tuple(value.replace('local', 'production') for value in key): response
                    for key, response in module.responses.items()}
arguments = [argument for argument in sys.argv[1:] if argument != '--json']
command = [sys.argv[0], '--json'] + arguments
returncode, stdout, stderr = module.run_command(command)
records = SNAPSHOT.decode_stream(stdout)
for record in records:
    print(json.dumps(record))
sys.exit(returncode)
