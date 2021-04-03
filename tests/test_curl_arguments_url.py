#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""
from typing import Dict, Any

import pytest
import yaml
import diskcache


from curl_arguments_url.curl_arguments_url import cli_args_to_cmd, parse_param_args, SwaggerEndpoint, Param, \
    SwaggerRepo, SwaggerModel, Raw
from curl_arguments_url import curl_arguments_url

# @pytest.fixture
# def response():
#     """Sample pytest fixture.
#
#     See more at: http://doc.pytest.org/en/latest/fixture.html
#     """
#     # import requests
#     # return requests.get('https://github.com/audreyr/cookiecutter-pypackage')


# def test_content(response):
#     """Sample pytest test function with the pytest fixture as an argument."""
#     # from bs4 import BeautifulSoup
#     # assert 'GitHub' in BeautifulSoup(response.content).title.string

TEST_SWAGGER_MODEL_YAML = """
apis:
- path: /get
  operations:
  - method: POST
    parameters:
    - name: foo
      paramType: query
- path: /{thing}/do
  operations:
  - method: GET
    parameters:
    - name: bang
      paramType: query
    - name: thing
      paramType: path
- path: /test/for/{missing}/path/param
  operations:
  - method: GET
    parameters:
    - name: query_param
      paramType: query
- path: /need/a/header/{for}/this
  operations:
  - method: GET
    parameters:
    - name: for
      paramType: path
    - name: header_param
      paramType: header
    - name: still_querying
      paramType: query
- path: /dashed/arg/name
  operations:
  - method: GET
    parameters:
    - name: Lots-O-Dashes
      paramType: query
- path: /posting/stuff
  operations:
  - method: POST
    parameters:
    - name: body
      paramType: body
      type: TestObj
- path: /posting/raw/stuff
  operations:
  - method: POST
    parameters:
    - name: form
      paramType: body
      type: ComplexObj
basePath: fake.com
models:
  TestObj:
    id: TestObj
    properties:
      arg_one:
        type: string
      arg_two:
        type: integer
  ComplexObj:
    id: ComplexObj
    properties:
      arg_list:
        type: array
      arg_list_int:
        type: array
        items:
          type: int
      arg_nested:
        type: whatevs
"""


@pytest.fixture()
def swagger_model():
    return SwaggerRepo(yaml.safe_load(TEST_SWAGGER_MODEL_YAML))


class MockCache:
    _cache: Dict[str, Any]
    directory: str

    def __init__(self, directory: str = ''):
        self._cache = {}
        self.directory = directory

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value


@pytest.fixture(autouse=True, scope='function')
def mock_cache(monkeypatch):
    mock_cache = MockCache()

    def get_mock_cache(directory: str) -> MockCache:
        mock_cache.directory = directory
        return mock_cache

    monkeypatch.setattr(curl_arguments_url, 'Cache', get_mock_cache)

    return mock_cache


@pytest.mark.parametrize('args,expected_cmd', [
    ('fake.com/get -X POST +foo=bar -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar -H auth'.split(' ')),

    ('fake.com/{thing}/do +bang boom +thing thingie'.split(' '),
     'curl -X GET fake.com/thingie/do?bang=boom'.split(' ')),

    ('fake.com/get -X POST +foo bar +foo bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),

    ('fake.com/get -X POST +foo bar bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),

    ('fake.com/test/for/{missing}/path/param +query_param query_val +missing found'.split(' '),
     'curl -X GET fake.com/test/for/found/path/param?query_param=query_val'.split(' ')),

    ('fake.com/need/a/header/{for}/this +header_param a-head +still_querying huh +for something'.split(' '),
     'curl -X GET fake.com/need/a/header/something/this?still_querying=huh'.split(' ') + ['-H', 'header_param: a-head']
     ),
    ('fake.com/dashed/arg/name +Lots-O-Dashes aDashOfPepper'.split(' '),
     'curl -X GET fake.com/dashed/arg/name?Lots-O-Dashes=aDashOfPepper'.split(' ')
     ),
    ('fake.com/posting/stuff --method POST +arg_one=val_one +arg_two 2'.split(' '),
     'curl -X POST fake.com/posting/stuff'.split(' ') + [
         '-H', 'Content-Type: application/json',
         '--data-binary', '{"arg_one": "val_one", "arg_two": 2}'
     ]),
    ('fake.com/posting/raw/stuff --method POST +arg_list one +arg_list two +arg_list_int 1'.split(' ') + [
        '+arg_nested', '{"A": 1, "B": 2}'
    ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
        '-H', 'Content-Type: application/json',
        '--data-binary', '{"arg_list": ["one", "two"], "arg_list_int": [1], "arg_nested": {"A": 1, "B": 2}}'
    ])
])
def test_cli_args_to_cmd_utl(swagger_model, args, expected_cmd):
    cmd, _ = cli_args_to_cmd(args, swagger_model)

    assert cmd == expected_cmd


def test_parse_param_args():
    # this specificall tests being able to have a .remaining arg
    class MockSwaggerEndpoint(SwaggerEndpoint):
        # noinspection PyMissingConstructor
        def __init__(self):
            pass

        params = {
            "anitem": [Param(name="anitem", param_type="query")],
            "remaining": [Param(name="remaining", param_type="query")]
        }

    args, curl_args = parse_param_args(
        MockSwaggerEndpoint(),
        "+anitem=thing +remaining=otherthings -- -H cookie".split(' ')
    )

    # assert args == argparse.Namespace(anitem=[["thing"]], remaining=[["otherthings"]])
    assert args.anitem[0].values == ["thing"]
    assert args.remaining[0].values == ["otherthings"]

    assert curl_args == ['-H', 'cookie']


@pytest.mark.parametrize('param_data,swagger_models,expected_params', [
    # Param(name, param_type, description, required, type_)
    ({'name': 'a-name', 'paramType': 'query'}, {}, [Param('a-name', 'query', '', False, str)]),
    ({'name': 'b-name', 'paramType': 'path', 'description': 'Boring description', 'required': True, 'type': 'integer'},
     {}, [Param('b-name', 'path', 'Boring description', True, int)]
     ),
    ({'name': 'c-name', 'paramType': 'post', 'type': 'Testy'},
     {'Testy': SwaggerModel(
         id='Testy',
         properties=[Param('c-name', 'json-post'), Param('d-name', 'json-post', type_=Raw)]
     )},
     [Param('c-name', 'json-post'), Param('d-name', 'json-post', type_=Raw)]),
])
def test_param_from_data(param_data, swagger_models, expected_params):
    actual_params = list(SwaggerEndpoint.param_from_data(param_data, swagger_models))

    assert actual_params == expected_params

