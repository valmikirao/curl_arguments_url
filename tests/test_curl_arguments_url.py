#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""
from copy import deepcopy
from typing import List, Tuple, Optional, Iterable

import pytest

from curl_arguments_url.curl_arguments_url import SwaggerRepo, CompletionItem


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


POSTING_URL_COMPLETIONS = [
    CompletionItem(tag='fake.com/posting/raw/stuff', description='Testing Spec'),
    CompletionItem(tag='fake.com/posting/stuff', description='Testing Spec')
]
ALL_URL_COMPLETIONS = [
    CompletionItem(tag='fake.com/completer', description='For Completion Tests'),
    CompletionItem(tag='fake.com/dashed/arg/name', description='Testing Spec'),
    CompletionItem(tag='fake.com/get', description='Testing Spec'),
    CompletionItem(tag='fake.com/has/multiple/methods', description='Path Summary'),
    CompletionItem(tag='fake.com/need/a/header/{for}/this', description='Testing Spec'),
    *POSTING_URL_COMPLETIONS,
    CompletionItem(tag='fake.com/{arg}/in/path/and/body', description='Testing Spec'),
    CompletionItem(tag='fake.com/{bad-thing}/do', description='Testing Spec'),
    CompletionItem(tag='fake.com/{thing}/do', description='Testing Spec')
]

FOOBAR_COMPLETION = CompletionItem(tag='+foobar', description=None)
FOO_PREFIXED_COMPLETIONS = [
    CompletionItem(tag='+foo', description='Foo!'),
    FOOBAR_COMPLETION
]
ALL_ARG_COMPLETIONS = [
    CompletionItem(tag='+bar', description='Bar!'),
    CompletionItem(tag='+barfoo', description=None),
    *FOO_PREFIXED_COMPLETIONS
]
GET_COMPLETION = CompletionItem(tag='GET', description='Get')
P_PREFIXED_METHOD_COMPLETIONS = [
    CompletionItem(tag='PATCH', description='For Completion Tests'),
    CompletionItem(tag='POST', description='For Completion Tests')
]
ALL_METHOD_COMPLETIONS = [
    CompletionItem(tag='DELETE', description='For Completion Tests'),
    GET_COMPLETION,
    *P_PREFIXED_METHOD_COMPLETIONS
]
ARG_PATH_AND_BODY_COMPLETIONS = [
    CompletionItem(tag='+arg:BODY', description='and in body'),
    CompletionItem(tag='+arg:PATH', description=None),
]
ALL_GENERIC_COMPLETIONS = [
    CompletionItem(tag='--no-run', description="Don't run the curl command.  Useful with -p"),
    CompletionItem(tag='--print-cmd', description='Print the resulting curl command to standard out'),
    CompletionItem(tag='-n', description="Don't run the curl command.  Useful with -p"),
    CompletionItem(tag='-p', description='Print the resulting curl command to standard out'),
]


TestGetCompletionsCase = Tuple[int, List[str], List[CompletionItem]]


class TestGetCompletionsParametrize:
    UPPER_AND_LOWER_CASES = [
            (1, ['carl', 'fake.com'], ALL_URL_COMPLETIONS),
            (1, ['carl', 'u'], [CompletionItem('utils', 'Utilities')]),
            (1, ['carl', 'fake.com/posting/'], POSTING_URL_COMPLETIONS),
            (2, ['carl', 'fake.com/completer', ''], ALL_METHOD_COMPLETIONS),
            (2, ['carl', 'fake.com/completer', 'P'], P_PREFIXED_METHOD_COMPLETIONS),
            (2, ['carl', 'fake.com/completer', 'GET'], [GET_COMPLETION]),
            (3, ['carl', 'fake.com/completer', 'GET', '+'], ALL_ARG_COMPLETIONS),
            (3, ['carl', 'fake.com/completer', 'GET', '+foo'], FOO_PREFIXED_COMPLETIONS),
            (3, ['carl', 'fake.com/completer', 'GET', '+foobar'], [FOOBAR_COMPLETION]),
            (5, ['carl', 'fake.com/completer', 'GET', '+barfoo', 'foo', '+foo'], FOO_PREFIXED_COMPLETIONS),
            (3, ['carl', 'fake.com/{arg}/in/path/and/body', 'POST', '+'], ARG_PATH_AND_BODY_COMPLETIONS),
            (4, ['carl', 'fake.com/{thing}/do', 'GET', '+thing', ''], [
                CompletionItem(tag=t, description=None) for t in (
                    'bar-thing', 'barfoo-thing', 'foo-thing', 'foobar-thing'
                )
            ]),
            (7, ['carl', 'fake.com/{thing}/do', 'GET', '+thing', 'block', '+bang', 'bar', 'foo'], [
                CompletionItem(tag=t, description=None) for t in ('foo-bang', 'foobar-bang')
            ]),
            (3, ['carl', 'fake.com/completer', 'POST', '-'], ALL_GENERIC_COMPLETIONS),
            (5, ['carl', 'fake.com/completer', 'POST', '+foo', 'some-val', '-'], ALL_GENERIC_COMPLETIONS)
    ]
    SIMPLE_CASES = [
            (4, ['carl', 'fake.com/completer', 'POST', '+foo', 'not-in-cache'], [
                CompletionItem(tag='not-in-cache', description=None)
            ]),
    ]

    @classmethod
    def get_cases(cls) -> Iterable[TestGetCompletionsCase]:
        for case in cls.UPPER_AND_LOWER_CASES:
            # test with both uppoer and lower
            case_upper = deepcopy(case)
            case_upper[1][-1] = case[1][-1].upper()
            yield case_upper

            case_lower = deepcopy(case)
            case_lower[1][-1] = case[1][-1].lower()
            yield case_lower
        for case in cls.SIMPLE_CASES:
            yield case


@pytest.mark.usefixtures('make_value_cache_ephemeral')
@pytest.mark.parametrize('index,words,expected', TestGetCompletionsParametrize.get_cases())
def test_get_completions(swagger_model: SwaggerRepo, index: int, words: List[str],
                         expected: List[Tuple[str, Optional[str]]]):

    # get some values in the cache
    arg_value_prefixes = ['foo', 'bar', 'foobar', 'barfoo']
    for prefix in arg_value_prefixes:
        swagger_model.cli_args_to_cmd([
            'fake.com/{thing}/do', 'GET',
            '+thing', f"{prefix}-thing", '+bang', f"{prefix}-bang"
        ])

    actual = swagger_model.get_completions(index, words)
    assert list(actual) == expected
