import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class LabAccessScriptTests(unittest.TestCase):
    def run_script(self, failure=''):
        artifact_dir = ROOT / '.ansible'
        artifact_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(artifact_dir)) as directory:
            work = Path(directory)
            binary = work / 'minio-client'
            fixture = Path(__file__).with_name('lab_minio_client.py')
            binary.write_bytes(fixture.read_bytes())
            binary.chmod(0o700)
            state_path = work / 'state.json'
            state_path.write_text(json.dumps({'objects': {}, 'calls': []}))
            environment = os.environ.copy()
            environment.update(PATH=str(work) + os.pathsep + environment['PATH'],
                               TMPDIR=str(work), LAB_CLIENT_STATE=str(state_path), LAB_CLIENT_FAILURE=failure)
            result = subprocess.run(['bash', str(ROOT / 'lab/check-access.sh')],
                                    env=environment, capture_output=True, text=True)
            state = json.loads(state_path.read_text())
            self.assertEqual(state['objects'], {}, result.stdout + result.stderr)
            self.assertFalse(any(call[0] in ('rb', 'mb') or '--recursive' in call for call in state['calls']))
            return result

    def test_successful_permissions_and_cleanup(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS:'), 8)

    def test_unexpected_permission_is_failure(self):
        result = self.run_script('allow')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('неожиданно разрешена', result.stderr)

    def test_network_failure_is_not_accepted_as_access_denial(self):
        result = self.run_script('network')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('другая ошибка', result.stderr)


if __name__ == '__main__':
    unittest.main()
