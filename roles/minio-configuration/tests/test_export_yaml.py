"""Verify readable export formatting without changing IAM values."""
import copy
import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('export_yaml', ROOT / 'filter_plugins/minio_configuration_export.py')
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


class ExportYamlTests(unittest.TestCase):
    def test_policy_and_entity_field_order_and_round_trip(self):
        statement = {'Resource': ['arn:aws:s3:::xxx', 'arn:aws:s3:::xxx/*'],
                     'Condition': {'StringEquals': {'custom': ['yes', 'null']}},
                     'Action': ['s3:GetObject', 's3:PutObject'], 'Effect': 'Allow', 'Sid': 'Read'}
        document = {'Statement': [statement], 'Version': '2012-10-17'}
        configuration = {
            'minio_configuration_users': [{'status': 'enabled', 'statements': [statement], 'name': 'reader'}],
            'minio_configuration_groups': [{'members': ['reader'], 'statements': [statement], 'name': 'staff'}],
            'minio_configuration_backets': [{'name': 'xxx', 'anonymous_policy': document, 'versioning': True}]}
        original = copy.deepcopy(configuration)
        output = EXPORT.export_yaml(configuration)
        parsed = yaml.safe_load(output)
        self.assertEqual(parsed, original)
        self.assertEqual(configuration, original)
        self.assertEqual(list(parsed), list(original))
        for entities in parsed.values():
            self.assertEqual(next(iter(entities[0])), 'name')
        for owner in parsed['minio_configuration_users'] + parsed['minio_configuration_groups']:
            self.assertEqual(list(owner['statements'][0]), ['Sid', 'Effect', 'Action', 'Resource', 'Condition'])
        anonymous_policy = parsed['minio_configuration_backets'][0]['anonymous_policy']
        self.assertEqual(list(anonymous_policy), ['Version', 'Statement'])
        self.assertEqual(list(anonymous_policy['Statement'][0]), ['Sid', 'Effect', 'Action', 'Resource', 'Condition'])
        self.assertRegex(output, r'(?m)^\s+Action: \[[^\n]*\]$')
        self.assertRegex(output, r'(?m)^\s+Resource: \[[^\n]*\]$')
        self.assertNotIn('statements: [', output)
        self.assertNotIn('Statement: [', output)
        self.assertNotIn('members: [', output)

    def test_special_yaml_strings_and_long_lists_remain_on_one_line(self):
        values = ['*', 'null', 'yes', 'a,b', 'x: y'] + ['arn:aws:s3:::bucket/object' + str(index) for index in range(20)]
        configuration = {'statements': [{'Effect': 'Deny', 'NotAction': values, 'NotResource': values}]}
        output = EXPORT.export_yaml(configuration)
        self.assertEqual(yaml.safe_load(output), configuration)
        for field in ['NotAction', 'NotResource']:
            lines = [line.strip() for line in output.splitlines() if line.strip().startswith(field + ':')]
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith(field + ': ['))
            self.assertTrue(lines[0].endswith(']'))
            self.assertIn('object19', lines[0])

    def test_optional_policy_fields_scalars_and_nested_order_are_preserved(self):
        condition = {'StringLike': {'s3:prefix': ['reports/*']}, 'Bool': {'aws:SecureTransport': 'true'}}
        statement = {'Extra': 'value', 'Condition': condition, 'Resource': '*', 'Action': 's3:GetObject',
                     'NotPrincipal': {'AWS': '*'}, 'Principal': {'AWS': ['*']}, 'Effect': 'Allow'}
        output = EXPORT.export_yaml({'Statement': [statement], 'Version': '2012-10-17'})
        parsed = yaml.safe_load(output)
        exported_statement = parsed['Statement'][0]
        self.assertEqual(exported_statement, statement)
        self.assertEqual(list(exported_statement), ['Effect', 'Principal', 'NotPrincipal', 'Action', 'Resource', 'Condition', 'Extra'])
        self.assertEqual(list(exported_statement['Condition']), list(condition))
        self.assertIn("Resource: '*'", output)
        self.assertIn('Action: s3:GetObject', output)


if __name__ == '__main__':
    unittest.main()
