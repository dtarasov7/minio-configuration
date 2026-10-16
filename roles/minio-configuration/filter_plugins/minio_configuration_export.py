"""Readable YAML exports with ordered fields and compact IAM value lists."""
import yaml

from ansible.parsing.yaml.dumper import AnsibleDumper
from yaml.nodes import SequenceNode


STATEMENT_FIELDS = ('Sid', 'Effect', 'Principal', 'NotPrincipal', 'Action', 'NotAction',
                    'Resource', 'NotResource', 'Condition')
INLINE_FIELDS = {'Action', 'NotAction', 'Resource', 'NotResource'}


def order_fields(value):
    if isinstance(value, list):
        return [order_fields(item) for item in value]
    if not isinstance(value, dict):
        return value

    if 'name' in value:
        preferred = ('name',)
    elif 'Statement' in value:
        preferred = ('Version', 'Statement')
    elif 'Effect' in value:
        preferred = STATEMENT_FIELDS
    else:
        preferred = ()
    keys = [key for key in preferred if key in value]
    keys.extend(key for key in value if key not in preferred)
    ordered = {}
    for key in keys:
        ordered[key] = order_fields(value[key])
    return ordered


class ExportDumper(AnsibleDumper):
    def represent_mapping(self, tag, mapping, flow_style=None):
        node = super().represent_mapping(tag, mapping, flow_style)
        for key, value in node.value:
            if key.value in INLINE_FIELDS and isinstance(value, SequenceNode):
                value.flow_style = True
        return node


def export_yaml(configuration):
    ordered = order_fields(configuration)
    return yaml.dump(ordered, Dumper=ExportDumper, default_flow_style=False,
                     sort_keys=False, allow_unicode=True, indent=2, width=2 ** 31 - 1)


class FilterModule:
    def filters(self):
        return {'minio_configuration_export_yaml': export_yaml}
