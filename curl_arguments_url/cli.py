"""Console script for curl_arguments_url."""
import sys
import shlex
import subprocess
import re
from typing import Tuple, List, NamedTuple

from curl_arguments_url.curl_arguments_url import SwaggerRepo, BashCompletionArgs

ZSH_SCRIPT = """\
#compdef carl

autoload -U compinit
compinit

_carl_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[carl] )) && return 1

    completions=("${(@f)$(carl utils zsh-completion "$CURRENT" "${words[*]}")}")

    if [ -n "completions" ]; then
        _describe -V unsorted completions -U
    fi
}

compdef _carl_completion carl;
"""

BASH_SCRIPT = """\
#/usr/bin/env bash

function _carl_completion() {
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD _CLICK_TEST_COMPLETE=bash_complete $1)
    response=$(carl utils bash-completion "$COMP_CWORD" ${COMP_WORDS[*]}") 
    COMPREPLY=response
  # readarray -t COMPREPLY < <(carl utils bash-completion "$COMP_CWORD" "$COMP_LINE")
  #COMPREPLY=($(carl utils bash-completion "$COMP_CWORD" "$COMP_LINE"))
}

complete -F _carl_completion carl
"""


class ProccessedBaseArgs(NamedTuple):
    word_index: int
    words: List[str]
    prefix_to_remove: str


def processes_bash_args(bash_args: BashCompletionArgs) -> ProccessedBaseArgs:
    if bash_args.line[-1] == '\\':
        # trailing backslashes cause shlex problems
        line = bash_args.line[:-1]
    else:
        line = bash_args.line

    try:
        words_from_line = shlex.split(line)
        raise Exception(line, words_from_line)
    except:
        raise Exception(line)

    from_line_i = 0
    cword_so_far = ''
    index_to_return = 0
    prefix_to_remove = ''

    for cwords_i, cword in enumerate(bash_args.passed_cwords):
        cword_so_far += cword
        if from_line_i >= len(words_from_line):
            words_from_line.append('')
        if cword_so_far == words_from_line[from_line_i]:
            if cwords_i == bash_args.word_index:
                index_to_return = from_line_i
                # prefix was the cword_so_far before we added to it
                if cword == ':':
                    # special colon case for bash's autocomplete
                    prefix_to_remove = cword_so_far
                else:
                    prefix_to_remove = cword_so_far[:-len(cword)]
            from_line_i += 1
            cword_so_far = ''

    return ProccessedBaseArgs(
        word_index=index_to_return,
        words=words_from_line,
        prefix_to_remove=prefix_to_remove
    )






def main() -> int:
    """Console script for curl_arguments_url."""

    swagger = SwaggerRepo()

    cmd, generic_args = swagger.cli_args_to_cmd(sys.argv[1:])

    if not generic_args.util:
        if generic_args.print_cmd:
            print(" ".join(shlex.quote(a) for a in cmd))
        try:
            if generic_args.run_cmd:
                subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            return e.returncode
        else:
            return 0
    else:
        if generic_args.zsh_completion_args is not None:
            index = generic_args.zsh_completion_args.word_index - 1
            words = shlex.split(generic_args.zsh_completion_args.line)
            completions = swagger.get_completions(
                index=index,
                words=words
            )
            for completion in completions:
                tag = completion.tag.replace(':', r'\:')
                if completion.description is not None:
                    print(f"{tag}:{completion.description}")
                else:
                    print(tag)
        elif generic_args.bash_completion_args is not None:
            processed_args = processes_bash_args(generic_args.bash_completion_args)
            completions = swagger.get_completions(
                index=processed_args.word_index,
                words=processed_args.words
            )

            for completion in completions:
                tag = completion.tag[len(processed_args.prefix_to_remove):]
                # regex stolen from shlex, except for some reason ':@=' are not escaped by shlex but don't play don't
                # play well with bash completion utility, so those are escaped here
                tag = re.sub(r'[^\w@%+=:,./-]', lambda x: '\\' + x.group(), tag, re.ASCII)
                print(tag)
        elif generic_args.zsh_print_script:
            print(ZSH_SCRIPT)
        elif generic_args.bash_print_script:
            print(BASH_SCRIPT)
        else:
            raise NotImplementedError()

        return 0


if __name__ == '__main__':
    exit(main())
