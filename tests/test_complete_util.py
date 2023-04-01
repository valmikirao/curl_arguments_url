import pytest

from curl_arguments_url.complete_util import get_base_args, get_describe_url_args
from curl_arguments_url.curl_arguments_url import SwaggerRepo

EXPECTED_BASE_ARGS = (
    '-X[Method used for the curl command and for completing the possible '
    'urls]:method:(get put post delete options head patch trace)\n'
    '--method[Method used for the curl command and for completing the possible '
    'urls]:method:(get put post delete options head patch trace)\n'
    '1:url:{_carl_url {url}}\n'
    '*::parameter:{_carl_params}\n'
)


def test_get_base_args():
    actual = get_base_args()
    assert actual == EXPECTED_BASE_ARGS


EXPECTED_GET_DESCRIBE_URL_ARGS = (
    'fake.com/{thing}/do\n'
    'fake.com/{bad-thing}/do\n'
    'fake.com/need/a/header/{for}/this\n'
    'fake.com/dashed/arg/name\n'
    'fake.com/has/multiple/methods:Path Description\n'
)


EXPECTED_POST_DESCRIBE_URL_ARGS = (
    'fake.com/get\n'
    'fake.com/posting/stuff\n'
    'fake.com/posting/raw/stuff\n'
    'fake.com/has/multiple/methods:Path Description\n'
)

EXPECTED_PATCH_DESCRIBE_URL_ARGS = 'fake.com/has/multiple/methods:Operation Summary\n'


@pytest.mark.parametrize('method,expected', [
    ('get', EXPECTED_GET_DESCRIBE_URL_ARGS),
    ('post', EXPECTED_POST_DESCRIBE_URL_ARGS),
    ('POST', EXPECTED_POST_DESCRIBE_URL_ARGS),
    ('patch', EXPECTED_PATCH_DESCRIBE_URL_ARGS)
])
def test_get_describe_url_args(swagger_model: SwaggerRepo, method: str, expected: str):
    actual = get_describe_url_args(method, swagger_model=swagger_model)
    assert actual == expected

