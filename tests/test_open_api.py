from typing import Optional, List, Set

import pytest

from curl_arguments_url.models.methods import METHODS
from curl_arguments_url.models import open_api


def test_path_item_methods():
    """
    Make sure every method is in the PathItem model
    """
    for method in METHODS:
        method_field = open_api.PathItem.__fields__[method.lower()]
        assert method_field.type_ is open_api.Operation
        assert not method_field.required


@pytest.mark.parametrize('parent_required,expected_required', [
    (None, {'prop1', 'prop4'}),
    ([], {'prop1', 'prop4'}),
    (['prop2'], {'prop1', 'prop2', 'prop4'})
])
def test_sub_schema_requires(parent_required: Optional[List[str]], expected_required: Set[str]):
    schema = open_api.Schema.parse_obj({
        'required': parent_required,
        'type': 'object',
        'properties': {
            'prop1': {
                'type': 'string',
                'required': True
            },
            'prop2': {
                'type': 'string',
                'required': False
            },
            'prop3': {
                'type': 'string',
            },
            'prop4': {
                'type': 'integer',
                'required': True
            }
        }
    })

    assert schema.type == 'object'
    assert set(schema.required or {}) == expected_required
