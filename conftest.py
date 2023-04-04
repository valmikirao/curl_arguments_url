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
