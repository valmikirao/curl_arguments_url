import shlex
from typing import Tuple, List

import pytest

from curl_arguments_url.cli import processes_bash_args, ProccessedBaseArgs
from curl_arguments_url.curl_arguments_url import BashCompletionArgs


@pytest.mark.parametrize('bash_args,expected',[
    # (BashCompletionArgs(word_index=3, line='carl http://', passed_cwords=['carl', 'http', ':', '//']),
    #  ProccessedBaseArgs(1, ['carl', 'http://'], 'http:')
    #  ),
    # (BashCompletionArgs(4, 'carl http://fake.com/get ', ['carl', 'http', ':', '//fake.com/get', '']),
    #  ProccessedBaseArgs(2, ['carl', 'http://fake.com/get', ''], '')
    #  ),
    # (BashCompletionArgs(4, 'carl http://fake.com/get POST', ['carl', 'http', ':', '//fake.com/get', 'POST']),
    #  ProccessedBaseArgs(2, ['carl', 'http://fake.com/get', 'POST'], '')
    #  ),
    # (BashCompletionArgs(4, 'carl http://fake.com/get POST +th', ['carl', 'http', ':', '//fake.com/get', 'POST']),
    #  ProccessedBaseArgs(2, ['carl', 'http://fake.com/get', 'POST', '+th'], '')
    #  ),
    (BashCompletionArgs(2, 'carl http:', ['carl', 'http', ':']),
     ProccessedBaseArgs(1, ['carl', 'http:'], 'http:')
     )
])
def test_processes_bash_args(bash_args: BashCompletionArgs, expected: Tuple[int, List[str]]):
    actual = processes_bash_args(bash_args)
    assert actual == expected
