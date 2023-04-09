from typing import List

import pytest

from curl_arguments_url.cli import line_to_words


@pytest.mark.parametrize('line,expected', [
    ('carl http://fake.com POST +arg value', ['carl', 'http://fake.com', 'POST', '+arg', 'value']),
    ('+arg1 sp\\ ace +arg2 "arg two" +arg3 \'arg "3"\'', ['+arg1', 'sp ace', '+arg2', 'arg two', '+arg3', 'arg "3"']),
    ('end with backslash\\', ['end', 'with', 'backslash']),
    ('"open double quotes', ['open double quotes']),
    ('open \'single\\ quotes', ['open', 'single\\ quotes'])
])
def test_line_to_words(line: str, expected: List[str]):
    actual = line_to_words(line)
    assert actual == expected
