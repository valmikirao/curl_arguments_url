"""Console script for curl_arguments_url."""
import sys
import shlex
import subprocess
from typing import List, Optional

from curl_arguments_url.curl_arguments_url import SwaggerRepo


ZSH_SCRIPT = """\
#compdef carl

autoload -U compinit
compinit

_carl() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[carl] )) && return 1

    completions=("${(@f)$(carl utils zsh-completion "$CURRENT" "${words[*]}")}")

    if [ -n "$completions" ]; then
        _describe -V unsorted completions -U
    fi
}

compdef _carl carl;
"""


def line_to_words(line: str) -> List[str]:
    """
    Parses the original line.  Preferrables, zsh would do this for you but de-escaping the values is challenging
    to say the least.  At least here I can write unit tests.  I'm basically allowing shlex to do all the work except
    if there is an open quote or a trailing "\"
    """
    if line[-1] == '\\':
        # trailing backslashes would cause errors
        line_ = line[:-1]
    else:
        line_ = line

    for suffix in ('', "'", '"'):
        # Try parsing.  If first it doesn't succeed, try with a closing quote, since that might be the problem
        try:
            return shlex.split(line_ + suffix)
        except ValueError:
            pass

    # hopefully don't get here, but in case we do, raise an honest exception which shows the problem with the
    # original string
    shlex.split(line)

    raise Exception("Shouldn't get here, but this exception keeps mypy happy")


def main(passed_argv: Optional[List[str]] = None) -> int:
    """Console script for curl_arguments_url."""
    if passed_argv is None:
        argv = sys.argv
    else:
        argv = passed_argv
    swagger = SwaggerRepo()

    cmd, generic_args = swagger.cli_args_to_cmd(argv[1:])

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
            words = line_to_words(generic_args.zsh_completion_args.line)
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
        elif generic_args.zsh_print_script:
            print(ZSH_SCRIPT)
        elif generic_args.values_list_params:
            for param in swagger.get_params_with_cached_values():
                print(param)
        elif generic_args.values_ls_for_param is not None:
            for value in swagger.get_ls_values_for_param(generic_args.values_ls_for_param):
                print(value)
        elif generic_args.values_rm_args is not None:
            param_name = generic_args.values_rm_args.param_name
            value = generic_args.values_rm_args.value
            swagger.remove_cached_value_for_param(param_name, value)
            print(f"Value {value!r} removed for param +{param_name}")
        elif generic_args.rebuild_cache:
            swagger.clear_all_spec_caches()
            SwaggerRepo(warnings=True)  # rebuilds the caches
        elif generic_args.values_add_args is not None:
            swagger.add_values(
                param_name=generic_args.values_add_args.param_name,
                values=generic_args.values_add_args.values
            )
        else:
            raise NotImplementedError()

        return 0


if __name__ == '__main__':
    exit(main())
