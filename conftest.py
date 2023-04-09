import os

import pytest

from curl_arguments_url.curl_arguments_url import SwaggerRepo


@pytest.fixture()
def content_root():
    content_root, _ = os.path.split(__file__)
    return content_root


@pytest.fixture()
def swagger_model(content_root):
    openapi_file = os.path.join(content_root, 'tests', 'resources', 'swagger', 'openapi-get-args-test.yml')
    return SwaggerRepo(files=[openapi_file], ephemeral=True)


@pytest.fixture()
def cache_param_values(swagger_model: SwaggerRepo) -> None:
    # get some values in the cache
    arg_value_prefixes = ['foo', 'bar', 'foobar', 'barfoo']
    for prefix in arg_value_prefixes:
        swagger_model.cli_args_to_cmd([
            'fake.com/{thing}/do', 'GET',
            '+thing', f"{prefix}-thing", '+bang', f"{prefix}-bang"
        ])
        swagger_model.cli_args_to_cmd([
            'fake.com/posting/raw/stuff', 'POST',
            '+arg_list', f"{prefix}-A", f"{prefix}-B", f"{prefix}-C",
            '+arg_nested', '{"A": 1, "B": "' + prefix + '-B-nested"}'
        ])
