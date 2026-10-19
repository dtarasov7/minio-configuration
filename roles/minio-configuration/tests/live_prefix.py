"""Run prefix-policy checks against a temporary, separate MinIO instance."""
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[3]


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def run(arguments, environment):
    result = subprocess.run(arguments, env=environment, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Command failed: ' + arguments[0] + ' ' + result.stderr[-1500:])
    return result.stdout


with tempfile.TemporaryDirectory(prefix='prefix-live-', dir=str(ROOT / '.ansible')) as directory:
    work = Path(directory)
    api_port, console_port = free_port(), free_port()
    endpoint = 'http://127.0.0.1:' + str(api_port)
    password = secrets.token_hex(24)
    environment = os.environ.copy()
    environment.update(MINIO_ROOT_USER='labadmin', MINIO_ROOT_PASSWORD=password,
                       MC_CONFIG_DIR=str(work / 'admin-client'), TMPDIR=str(work),
                       MINIO_LAB_ENDPOINT=endpoint)
    data = work / 'data'
    data.mkdir()
    with (work / 'server.log').open('w') as log:
        server = subprocess.Popen([
            '/usr/bin/minio', '--config-dir', str(work / 'server-config'),
            '--certs-dir', str(work / 'certs'), 'server', '--address', '127.0.0.1:' + str(api_port),
            '--console-address', '127.0.0.1:' + str(console_port), str(data)],
            env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Temporary MinIO exited before becoming ready')
                try:
                    with urllib.request.urlopen(endpoint + '/minio/health/live', timeout=1):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError('Temporary MinIO did not become ready')
            run(['minio-client', 'alias', 'set', 'lab', endpoint, 'labadmin', password], environment)
            run(['minio-client', 'mb', 'lab/lab-other'], environment)
            run(['minio-client', 'admin', 'user', 'add', 'lab', 'lab-test', 'Test-Only-123'], environment)
            inventory = yaml.safe_load((ROOT / 'lab/group_vars/minio_cluster/minio-config.yml').read_text())
            user = next(user for user in inventory['minio_configuration_users'] if user['name'] == 'lab-test')
            for statement in user['statements']:
                name = 'test-' + statement['Sid']
                path = work / (name + '.json')
                path.write_text(json.dumps({'Version': '2012-10-17', 'Statement': [statement]}))
                run(['minio-client', 'admin', 'policy', 'create', 'lab', name, str(path)], environment)
                run(['minio-client', 'admin', 'policy', 'attach', 'lab', name, '--user', 'lab-test'], environment)
            output = run(['bash', str(ROOT / 'lab/check-access.sh')], environment)
            print(output, flush=True)

            role = ROOT / 'roles/minio-configuration'
            spec = importlib.util.spec_from_file_location('snapshot', role / 'library/minio_configuration_snapshot.py')
            snapshot_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(snapshot_module)

            class Module:
                params = {'binary': '/usr/bin/minio-client', 'alias': 'lab'}

                def run_command(self, command):
                    response = subprocess.run(command, env=environment, capture_output=True, text=True)
                    return response.returncode, response.stdout, response.stderr

            snapshot = snapshot_module.Snapshot(Module()).collect_matrix()
            spec = importlib.util.spec_from_file_location('matrix', role / 'filter_plugins/minio_configuration_matrix.py')
            matrix_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(matrix_module)
            report = matrix_module.access_matrix(snapshot)
            rows = {row['resource']: row for row in csv.DictReader(io.StringIO(report['csv']), delimiter=';')}
            assert rows['lab-other/*']['u:lab-test'] == '-  R  -  -'
            assert rows['lab-other/other/*']['u:lab-test'] == 'L  R  W  D'
            print('PASS: real mc JSON collection and prefix-conditioned matrix', flush=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
