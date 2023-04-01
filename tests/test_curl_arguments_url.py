#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""

import pytest

from curl_arguments_url.curl_arguments_url import cli_args_to_cmd, parse_param_args, SwaggerEndpoint, CarlParam


@pytest.mark.parametrize('args,expected_cmd', [
    ('-X POST fake.com/get +foo=bar -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar -H auth'.split(' ')),

    ('fake.com/{thing}/do +bang boom +thing thingie'.split(' '),
     'curl -X GET fake.com/thingie/do?bang=boom'.split(' ')),

    # if they forget to add the path param
    ('fake.com/{bad-thing}/do +bang boom +bad-thing thang'.split(' '),
     'curl -X GET fake.com/thang/do?bang=boom'.split(' ')),

    ('-X POST fake.com/get +foo bar +foo bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),

    ('-X POST fake.com/get +foo bar bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),


    ('fake.com/need/a/header/{for}/this +header_param a-head +still_querying huh +for something'.split(' '),
     'curl -X GET fake.com/need/a/header/something/this?still_querying=huh'.split(' ') + ['-H', 'header_param: a-head']
     ),
    ('fake.com/dashed/arg/name +Lots-O-Dashes aDashOfPepper'.split(' '),
     'curl -X GET fake.com/dashed/arg/name?Lots-O-Dashes=aDashOfPepper'.split(' ')
     ),
    ('--method POST fake.com/posting/stuff +arg_one=val_one +arg_two 2'.split(' '),
     'curl -X POST fake.com/posting/stuff'.split(' ') + [
         '-H', 'Content-Type: application/json',
         '--data-binary', '{"arg_one": "val_one", "arg_two": 2}'
     ]),
    ('--method POST fake.com/posting/raw/stuff +arg_list one +arg_list two +arg_list_int 1'.split(' ') + [
        '+arg_nested', '{"A": 1, "B": 2}', '+array_nested', '[1, 2]', '[3, 4]'
    ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
        '-H', 'Content-Type: application/json',
        '--data-binary',
        '{"arg_list": ["one", "two"], "arg_list_int": [1], "arg_nested": {"A": 1, "B": 2},'
        ' "array_nested": [[1, 2], [3, 4]]}'
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
