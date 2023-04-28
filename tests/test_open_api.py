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


def test_schema_depth_array():
    schema = open_api.Schema.parse_obj({
        'type': 'array',
        'items': {
            'type': 'array',
            'items': {
                'type': 'array',
                'items': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': {'type': 'string'}
                    }
                }
            }
        }
    })

    assert schema.depth == 0
    assert schema.type == 'array'
    assert schema.items
    assert schema.items.depth == 1
    assert schema.items.type == 'array'
    assert schema.items.items
    assert schema.items.items.depth == 2
    assert schema.items.items.type == 'array'
    assert schema.items.items.items
    assert schema.items.items.items.depth == 3
    assert schema.items.items.items.type is None
    assert schema.items.items.items.items is None


def test_schema_depth_obj():
    schema = open_api.Schema.parse_obj({
        'type': 'object',
        'properties': {
            'prop1': {
                'type': 'object',
                'properties': {
                    'prop2': {
                        'type': 'object',
                        'properties': {
                            'prop3': {
                                'type': 'object',
                                'properties': {
                                    'prop4': {'type': 'string'}
                                }
                            }
                        }
                    }
                }
            }
        }
    })

    assert schema.depth == 0
    assert schema.type == 'object'
    assert schema.properties
    assert 'prop1' in schema.properties
    assert schema.properties['prop1'].depth == 1
    assert schema.properties['prop1'].type == 'object'
    assert schema.properties['prop1'].properties
    assert 'prop2' in schema.properties['prop1'].properties
    assert schema.properties['prop1'].properties['prop2'].depth == 2
    assert schema.properties['prop1'].properties['prop2'].type == 'object'
    assert schema.properties['prop1'].properties['prop2'].properties
    assert 'prop3' in schema.properties['prop1'].properties['prop2'].properties
    assert schema.properties['prop1'].properties['prop2'].properties['prop3'].depth == 3
    assert schema.properties['prop1'].properties['prop2'].properties['prop3'].type is None
    assert schema.properties['prop1'].properties['prop2'].properties['prop3'].properties is None


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
