#!/usr/bin/env python

"""Tests for `curl_arguments_url` package."""
import argparse
import io
import itertools
import re
import sys
from copy import deepcopy
from typing import List, Tuple, Optional, Iterable, NamedTuple, Any
from unittest.mock import MagicMock, ANY

import pytest

from curl_arguments_url.curl_arguments_url import SwaggerRepo, CompletionItem, GENERIC_OPTIONAL_ARGS

ALL_PATHS = [
    '/completer',
    '/dashed/arg/name',
    '/get',
    '/has/multiple/methods',
    '/need/a/header/{for}/this',
    '/posting/raw/stuff',
    '/posting/stuff',
    '/required/{path-arg}',
    '/{arg}/in/path/and/body',
    '/{bad-thing}/do',
    '/{thing}/do'
]

ALL_SERVERS = [
    'fake.com',
    'http://fake.com',
    'http://{foo}.com',
    'http://fake1.com'
]

ALL_URLS = sorted(serv + path for serv, path in itertools.product(ALL_SERVERS, ALL_PATHS))


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
        '+arg_nested', '{"A": 1, "B": "two"}', '+array_nested', '[1, 2]', '[3, 4]'
    ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
        '-H', 'Content-Type: application/json',
        '--data-binary',
        '{"arg_list": ["one", "two"], "arg_list_int": [1], "arg_nested": {"A": 1, "B": "two"},'
        ' "array_nested": [[1, 2], [3, 4]]}'
    ]),
    ('fake.com/posting/raw/stuff POST +arg_list one +arg_list two +arg_list_int 1'.split(' ') + [
        '+arg_nested', '{"A": 1, "B": "two"}', '+array_nested', '[1, 2]', '[3, 4]',
        '--body', '{"arg_list": ["over", "written"], "arg_nested": {"over": "written"},'
                  ' "xtra-arg": ["not", "over", "written"]}'
    ], 'curl -X POST fake.com/posting/raw/stuff'.split(' ') + [
        '-H', 'Content-Type: application/json',
        '--data-binary',
        '{"arg_list": ["one", "two"], "arg_nested": {"A": 1, "B": "two"}, "xtra-arg": ["not", "over", "written"], '
        '"arg_list_int": [1], "array_nested": [[1, 2], [3, 4]]}'
    ]),
    ('fake.com/{arg}/in/path/and/body POST +arg:PATH path_value +arg:BODY body_value'.split(' '),
     'curl -X POST fake.com/path_value/in/path/and/body'.split(' ') + [
         '-H', 'Content-Type: application/json',
         '--data-binary', '{"arg": "body_value"}'
    ]),
    ('fake.com/required/{path-arg} GET -nR +optional-arg value'.split(' '),
     'curl -X GET fake.com/required/?optional-arg=value'.split(' ')),
    ('http://fake1.com/get POST +foo thang'.split(' '),
     'curl -X POST http://fake1.com/get?foo=thang'.split(' ')),
    ('http://{foo}.com/get POST +foo:QUERY bar +foo:PATH fake2'.split(' '),
     'curl -X POST http://fake2.com/get?foo=bar'.split(' '))
])
def test_cli_args_to_cmd(swagger_model: SwaggerRepo, args: List[str], expected_cmd: List[str]):
    cmd, _ = swagger_model.cli_args_to_cmd(args)
    assert cmd == expected_cmd


class MockArgParseError(Exception):
    pass


def test_cli_args_to_cmd_missing_required(swagger_model: SwaggerRepo, monkeypatch):
    monkeypatch.setattr(argparse.ArgumentParser, 'error', MagicMock(side_effect=MockArgParseError()))

    cli_args = 'fake.com/required/{path-arg} GET -n +optional-arg value'.split()
    try:
        swagger_model.cli_args_to_cmd(cli_args)
        raise AssertionError('Shouln\'t get here: should error out')
    except MockArgParseError:
        # errored as expected
        pass


GENERIC_OPTIONAL_NAME_OR_FLAGS = list(itertools.chain(*(a.name_or_flags for a in GENERIC_OPTIONAL_ARGS)))
GENERIC_OPTIONAL_HELPS = [a.kwargs['help'] for a in GENERIC_OPTIONAL_ARGS]
PARAM_ARGS = [r'\+foo', r'\+foobar', r'\+bar', r'\+barfoo']
PARAM_ARGS_HELP = [r'Foo\!', r'Bar\!']


def escape_help_re(help_text: str) -> str:
    help_text = re.escape(help_text)
    # don't care about whitespace.  Note: The above escapes the whitespace, so the regex accounts for that
    help_text = re.sub(r'(\\\s)+', lambda _: r'\s+', help_text)
    return help_text


@pytest.mark.parametrize('args,expected_regexes', [  # expected is a list of regexes to match to
    (['--help'], ALL_URLS),
    (['fake.com/completer', '--help'], ['GET', 'POST', 'DELETE', 'PATCH']),
    (['fake.com/completer', 'GET', '--help'],
     GENERIC_OPTIONAL_NAME_OR_FLAGS
     + [escape_help_re(h) for h in GENERIC_OPTIONAL_HELPS]
     + PARAM_ARGS + PARAM_ARGS_HELP)
])
def test_help(swagger_model: SwaggerRepo, monkeypatch, args: List[str], expected_regexes: List[str]):
    output_io = io.StringIO()
    with monkeypatch.context() as monkypatch_:
        monkypatch_.setattr(sys, 'stdout', output_io)
        try:
            swagger_model.cli_args_to_cmd(args)
        except SystemExit:
            pass

    actual_output = output_io.getvalue()

    assert len(expected_regexes) > 1
    for expected_regex in expected_regexes:
        assert re.search(expected_regex, actual_output), f"Did not find {expected_regex!r} in output"


POSTING_URL_COMPLETIONS = [
    CompletionItem(tag='fake.com/posting/raw/stuff', description='Testing Spec'),
    CompletionItem(tag='fake.com/posting/stuff', description='Testing Spec')
]
ALL_FAKE_COM_URL_COMPLETIONS = [
    CompletionItem(tag='fake.com/completer', description='For Completion Tests'),
    CompletionItem(tag='fake.com/dashed/arg/name', description='Testing Spec'),
    CompletionItem(tag='fake.com/get', description='Testing Spec'),
    CompletionItem(tag='fake.com/has/multiple/methods', description='Path Summary'),
    CompletionItem(tag='fake.com/need/a/header/{for}/this', description='Testing Spec'),
    *POSTING_URL_COMPLETIONS,
    CompletionItem(tag='fake.com/required/{path-arg}', description='Testing Spec'),
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
    CompletionItem(tag='--body', description='Base json object to send in the body.  Required body params are still'
                                             ' required unless -R option passed.  Useful for dealing with incomplete'
                                             ' specs.'),
    CompletionItem(tag='--body-json', description='Base json object to send in the body.  Required body params are'
                                                  ' still required unless -R option passed.  Useful for dealing with'
                                                  ' incomplete specs.'),
    CompletionItem(
        tag='--no-requires',
        description="Don't check to see if required parameter values are missing or if values are one of the"
                    " enumerated values"
    ),
    CompletionItem(tag='--no-run', description="Don't run the curl command.  Useful with -p"),
    CompletionItem(tag='--print-cmd', description='Print the resulting curl command to standard out'),
    CompletionItem(
        tag='-R',
        description="Don't check to see if required parameter values are missing or if values are one of the"
                    " enumerated values"
    ),
    CompletionItem(tag='-b', description='Base json object to send in the body.  Required body params are still'
                                         ' required unless -R option passed.  Useful for dealing with incomplete'
                                         ' specs.'),
    CompletionItem(tag='-n', description="Don't run the curl command.  Useful with -p"),
    CompletionItem(tag='-p', description='Print the resulting curl command to standard out')
]


TestGetCompletionsCase = Tuple[int, List[str], List[CompletionItem]]


TestGetCompletionsParam = Tuple[int, List[str], List[CompletionItem]]


class GetCompletionsParametrize(NamedTuple):
    upper_and_lower_cases: List[TestGetCompletionsParam] = []
    simple_cases: List[TestGetCompletionsParam] = []

    def get_cases(self) -> Iterable[TestGetCompletionsCase]:
        for case in self.upper_and_lower_cases:
            # test with both uppoer and lower
            case_upper = deepcopy(case)
            case_upper[1][-1] = case[1][-1].upper()
            yield case_upper

            case_lower = deepcopy(case)
            case_lower[1][-1] = case[1][-1].lower()
            yield case_lower
        for case in self.simple_cases:
            yield case

    def parametrize(self) -> Any:
        return pytest.mark.parametrize('index,words,expected', self.get_cases())


get_completions_parametrize = GetCompletionsParametrize(
    upper_and_lower_cases=[
        (1, ['carl', 'fake.com'], ALL_FAKE_COM_URL_COMPLETIONS),
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
        (5, ['carl', 'fake.com/completer', 'POST', '+foo', 'some-val', '-'], ALL_GENERIC_COMPLETIONS),
        (3, ['carl', 'utils', 'cached-values', ''], [
            CompletionItem(tag='add', description='Add one or more values for a param to the cache'),
            CompletionItem(tag='ls', description='List all the values cached for a particular param'),
            CompletionItem(tag='params', description='List all the param names that have values cached'),
            CompletionItem(tag='rm', description='Remove a value for an param from the cache for completions')
        ]),
        (5, ['carl', 'utils', 'cached-values', 'rm', 'bang', 'foo'], [
            CompletionItem(tag=t, description=None) for t in ('foo-bang', 'foobar-bang')
        ]),
        (4, ['carl', 'fake.com/posting/raw/stuff', 'POST', '+arg_nested', '{"A": 1, "B": "foo'], [
            CompletionItem(tag='{"A": 1, "B": "foo-B-nested"}', description=None),
            CompletionItem(tag='{"A": 1, "B": "foobar-B-nested"}', description=None),
        ]),
        (4, ['carl', 'fake.com/completer', 'DELETE', '+foo', ''], [
            CompletionItem(tag=t, description=None) for t in ('bar1', 'bar2', 'foo1', 'foo2')
        ]),
        (4, ['carl', 'fake.com/completer', 'DELETE', '+foo', 'ba'], [
            CompletionItem(tag=t, description=None) for t in ('bar1', 'bar2')
        ]),
        (1, ['carl', 'http:'], [
            CompletionItem(tag=t, description=ANY) for t in ALL_URLS if t.startswith('http://')
        ])
    ],
    simple_cases=[
        (4, ['carl', 'fake.com/completer', 'POST', '+foo', 'not-in-cache'], [
            CompletionItem(tag='not-in-cache', description=None)
        ]),
    ]
)


@pytest.mark.usefixtures('cache_param_values')
@get_completions_parametrize.parametrize()
def test_get_completions(swagger_model: SwaggerRepo, index: int, words: List[str],
                         expected: List[Tuple[str, Optional[str]]]):

    actual = swagger_model.get_completions(index, words)
    assert list(actual) == expected


get_completions_2_parametrize = GetCompletionsParametrize(
    upper_and_lower_cases=[
        (1, ['carl', 'server-'], [
            CompletionItem(tag='server-op.com/path-servers', description='Testing Spec'),
            CompletionItem(tag='server-path.com/path-servers', description='Testing Spec'),
            CompletionItem(tag='server-root.com/no-servers', description='Testing Spec'),
        ]),
        (2, ['carl', 'server-path.com/path-servers', ''], [
            CompletionItem('GET', description='Testing Spec')
        ])
    ]
)


@get_completions_2_parametrize.parametrize()
def test_get_completions_2(swagger_model_2: SwaggerRepo, index: int, words: List[str],
                           expected: List[Tuple[str, Optional[str]]]):

    actual = swagger_model_2.get_completions(index, words)
    assert list(actual) == expected


@pytest.mark.usefixtures('cache_param_values')
def test_get_params_with_cached_values(swagger_model: SwaggerRepo):
    expected = ['arg_list', 'arg_nested', 'bang', 'thing']
    actual = swagger_model.get_params_with_cached_values()
    assert actual == expected


@pytest.mark.usefixtures('cache_param_values')
@pytest.mark.parametrize('remove_values,remaining_values,remaining_params', [
    (['barfoo-bang'], ['foobar-bang', 'bar-bang', 'foo-bang'], ['arg_list', 'arg_nested', 'bang', 'thing']),
    (['barfoo-bang', 'foobar-bang', 'bar-bang', 'foo-bang'], [''], ['arg_list', 'arg_nested', 'thing']),
])
def test_remove_param_cached_value(swagger_model: SwaggerRepo, remove_values: List[str], remaining_values: List[str],
                                   remaining_params: List[str]):
    initial_params = ['arg_list', 'arg_nested', 'bang', 'thing']
    actual_params = swagger_model.get_params_with_cached_values()
    assert actual_params == initial_params

    initial_values = ['barfoo-bang', 'foobar-bang', 'bar-bang', 'foo-bang']
    values_for_bang = swagger_model.get_completions_for_values_for_param('bang', prefix='')
    assert [v.tag for v in values_for_bang] == initial_values

    for value_to_remove in remove_values:
        swagger_model.remove_cached_value_for_param('bang', value_to_remove)

    actual_remaining_values = swagger_model.get_completions_for_values_for_param('bang', prefix='')
    assert [v.tag for v in actual_remaining_values] == remaining_values

    actual_remaining_params = swagger_model.get_completions_for_values_for_param('bang', prefix='')
    assert [v.tag for v in actual_remaining_params] == remaining_values


@pytest.fixture()
def initial_arg_nested_cached_values(swagger_model: SwaggerRepo) -> List[str]:
    initial_values = [
        '{"A": 1, "B": "barfoo-B-nested"}',
        '{"A": 1, "B": "foobar-B-nested"}',
        '{"A": 1, "B": "bar-B-nested"}',
        '{"A": 1, "B": "foo-B-nested"}'
    ]
    actual_initial_values = swagger_model.get_completions_for_values_for_param('arg_nested', prefix='')
    assert [v.tag for v in actual_initial_values] == initial_values

    return initial_values


@pytest.mark.usefixtures('cache_param_values', 'initial_arg_nested_cached_values')
def test_remove_complex_value(swagger_model: SwaggerRepo):
    swagger_model.remove_cached_value_for_param('arg_nested', '{"A": 1, "B": "foobar-B-nested"}')
    remaining_values = [
        '{"A": 1, "B": "barfoo-B-nested"}',
        '{"A": 1, "B": "bar-B-nested"}',
        '{"A": 1, "B": "foo-B-nested"}'
    ]
    actual_remaining_values = swagger_model.get_completions_for_values_for_param('arg_nested', prefix='')
    assert [v.tag for v in actual_remaining_values] == remaining_values


@pytest.mark.usefixtures('cache_param_values', 'initial_arg_nested_cached_values')
def test_add_complex_value(swagger_model: SwaggerRepo):
    swagger_model.add_values('arg_nested', values=[
        '{"cache": "this"}',
        'something-simple'
    ])
    remaining_values = [
        'something-simple',
        '{"cache": "this"}',
        '{"A": 1, "B": "barfoo-B-nested"}',
        '{"A": 1, "B": "foobar-B-nested"}',
        '{"A": 1, "B": "bar-B-nested"}',
        '{"A": 1, "B": "foo-B-nested"}'
    ]
    actual_remaining_values = swagger_model.get_completions_for_values_for_param('arg_nested', prefix='')
    assert [v.tag for v in actual_remaining_values] == remaining_values


def test_empty(monkeypatch):
    """ Don't error if there are no files """
    swagger_model = SwaggerRepo(files=[], ephemeral=True)
    try:
        with monkeypatch.context() as monkypatch_:
            monkypatch_.setattr(sys, 'stdout', MagicMock())  # don't want the help output here
            swagger_model.cli_args_to_cmd(['--help'])
    except SystemExit as x:
        assert x.code == 0

    assert list(swagger_model.get_completions(1, ['carl', ''])) == [
        CompletionItem('utils', description='Utilities')
    ]
