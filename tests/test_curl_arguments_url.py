#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""
from typing import List

import pytest

from curl_arguments_url.curl_arguments_url import SwaggerRepo


@pytest.mark.parametrize('args,expected_cmd', [
    ('fake.com/get POST +foo=bar -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar -H auth'.split(' ')),

    ('fake.com/{thing}/do GET +bang boom +thing thingie'.split(' '),
     'curl -X GET fake.com/thingie/do?bang=boom'.split(' ')),

    # if they forget to add the path param
    ('fake.com/{bad-thing}/do GET +bang boom +bad-thing thang'.split(' '),
     'curl -X GET fake.com/thang/do?bang=boom'.split(' ')),

    ('fake.com/get POST +foo bar +foo bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),

    ('fake.com/get POST +foo bar bing -- -H auth'.split(' '),
     'curl -X POST fake.com/get?foo=bar&foo=bing -H auth'.split(' ')),


    ('fake.com/need/a/header/{for}/this GET +header_param a-head +still_querying huh +for something'.split(' '),
     'curl -X GET fake.com/need/a/header/something/this?still_querying=huh'.split(' ') + ['-H', 'header_param: a-head']
     ),
    ('fake.com/dashed/arg/name GET +Lots-O-Dashes aDashOfPepper'.split(' '),
     'curl -X GET fake.com/dashed/arg/name?Lots-O-Dashes=aDashOfPepper'.split(' ')
     ),
    ('fake.com/posting/stuff POST +arg_one=val_one +arg_two 2'.split(' '),
     'curl -X POST fake.com/posting/stuff'.split(' ') + [
         '-H', 'Content-Type: application/json',
         '--data-binary', '{"arg_one": "val_one", "arg_two": 2}'
    ]),
    ('fake.com/posting/raw/stuff POST +arg_list one +arg_list two +arg_list_int 1'.split(' ') + [
        '+arg_nested', '{"A": 1, "B": 2}', '+array_nested', '[1, 2]', '[3, 4]'
    ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
        '-H', 'Content-Type: application/json',
        '--data-binary',
        '{"arg_list": ["one", "two"], "arg_list_int": [1], "arg_nested": {"A": 1, "B": 2},'
        ' "array_nested": [[1, 2], [3, 4]]}'
    ]),
    ('fake.com/{arg}/in/path/and/body POST +arg:PATH path_value +arg:BODY body_value'.split(' '),
     'curl -X POST fake.com/path_value/in/path/and/body'.split(' ') + [
         '-H', 'Content-Type: application/json',
         '--data-binary', '{"arg": "body_value"}'
    ])
])
def test_cli_args_to_cmd(swagger_model: SwaggerRepo, args: List[str], expected_cmd: List[str]):
    cmd, _ = swagger_model.cli_args_to_cmd(args)

    assert cmd == expected_cmd
