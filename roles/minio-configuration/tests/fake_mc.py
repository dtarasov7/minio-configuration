#!/usr/bin/env python3
"""Read-only mc fixture for the local Ansible export integration test."""
import json
import sys
from test_snapshot import FakeModule

if sys.argv[1:4] == ['alias', 'set', 'production'] or sys.argv[1:] == ['admin', 'info', 'production']:
    print('{}')
    sys.exit(0)

module = FakeModule()
module.params = {'binary': '/mc', 'alias': 'production'}
module.responses = {tuple(value.replace('local', 'production') for value in key): response
                    for key, response in module.responses.items()}
returncode, stdout, stderr = module.run_command(sys.argv)
print(stdout)
sys.exit(returncode)
