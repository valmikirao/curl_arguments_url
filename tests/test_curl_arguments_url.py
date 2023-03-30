#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""
import os
from typing import Dict, Any

import pytest
import yaml


from curl_arguments_url.curl_arguments_url import cli_args_to_cmd, parse_param_args, SwaggerEndpoint, CarlParam, \
    SwaggerRepo, SwaggerModel, Raw


@pytest.fixture()
def swagger_model():
    content_root = __file__
    for _ in (1, 2):
        # content root is this file dirs parent di
        content_root, _ = os.path.split(content_root)
    openapi_file = os.path.join(content_root, 'tests', 'resources', 'openapi-get-args-test.yml')
    return SwaggerRepo(files=[openapi_file])


@pytest.mark.parametrize('args,expected_cmd', [
    ('fake.com/get -X POST +foo=bar -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar -H auth'.split(' ')),

    # ('fake.com/{thing}/do +bang boom +thing thingie'.split(' '),
    #  'curl -X GET fake.com/thingie/do?bang=boom'.split(' ')),
    #
    # ('fake.com/get -X POST +foo bar +foo bing -- -H auth'.split(' '),
    #  'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),
    #
    # ('fake.com/get -X POST +foo bar bing -- -H auth'.split(' '),
    #  'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),
    #
    # ('fake.com/test/for/{missing}/path/param +query_param query_val +missing found'.split(' '),
    #  'curl -X GET fake.com/test/for/found/path/param?query_param=query_val'.split(' ')),
    #
    # ('fake.com/need/a/header/{for}/this +header_param a-head +still_querying huh +for something'.split(' '),
    #  'curl -X GET fake.com/need/a/header/something/this?still_querying=huh'.split(' ') + ['-H', 'header_param: a-head']
    #  ),
    # ('fake.com/dashed/arg/name +Lots-O-Dashes aDashOfPepper'.split(' '),
    #  'curl -X GET fake.com/dashed/arg/name?Lots-O-Dashes=aDashOfPepper'.split(' ')
    #  ),
    # ('fake.com/posting/stuff --method POST +arg_one=val_one +arg_two 2'.split(' '),
    #  'curl -X POST fake.com/posting/stuff'.split(' ') + [
    #      '-H', 'Content-Type: application/json',
    #      '--data-binary', '{"arg_one": "val_one", "arg_two": 2}'
    #  ]),
    # ('fake.com/posting/raw/stuff --method POST +arg_list one +arg_list two +arg_list_int 1'.split(' ') + [
    #     '+arg_nested', '{"A": 1, "B": 2}'
    # ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
    #     '-H', 'Content-Type: application/json',
    #     '--data-binary', '{"arg_list": ["one", "two"], "arg_list_int": [1], "arg_nested": {"A": 1, "B": 2}}'
    # ])
])
def test_cli_args_to_cmd_utl(swagger_model, args, expected_cmd):
    cmd, _ = cli_args_to_cmd(args, swagger_model)

    assert cmd == expected_cmd


@pytest.mark.skip
def test_parse_param_args():
    # this specificall tests being able to have a .remaining arg
    class MockSwaggerEndpoint(SwaggerEndpoint):
        # noinspection PyMissingConstructor
        def __init__(self):
            pass

        params = {
            "anitem": [CarlParam(name="anitem", param_type="query")],
            "remaining": [CarlParam(name="remaining", param_type="query")]
        }

    args, curl_args = parse_param_args(
        MockSwaggerEndpoint(),
        "+anitem=thing +remaining=otherthings -- -H cookie".split(' ')
    )

    # assert args == argparse.Namespace(anitem=[["thing"]], remaining=[["otherthings"]])
    assert args.anitem[0].values == ["thing"]
    assert args.remaining[0].values == ["otherthings"]

    assert curl_args == ['-H', 'cookie']


@pytest.mark.skip
@pytest.mark.parametrize('param_data,swagger_models,expected_params', [
    # Param(name, param_type, description, required, type_)
    # ({'name': 'a-name', 'paramType': 'query'}, {}, [CarlParam('a-name', 'query', '', False, str)]),
    # ({'name': 'b-name', 'paramType': 'path', 'description': 'Boring description', 'required': True, 'type': 'integer'},
    #  {}, [CarlParam('b-name', 'path', 'Boring description', True, int)]
    #  ),
    # ({'name': 'c-name', 'paramType': 'post', 'type': 'Testy'},
    #  {'Testy': SwaggerModel(
    #      id='Testy',
    #      properties=[CarlParam('c-name', 'json-post'), CarlParam('d-name', 'json-post', type_=Raw)]
    #  )},
    #  [CarlParam('c-name', 'json-post'), CarlParam('d-name', 'json-post', type_=Raw)]),
])
def test_param_from_data(param_data, swagger_models, expected_params):
    actual_params = list(SwaggerEndpoint.param_from_data(param_data, swagger_models))

    assert actual_params == expected_params

