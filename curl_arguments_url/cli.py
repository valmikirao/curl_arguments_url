"""Console script for curl_arguments_url."""
import sys
import shlex
import subprocess

from curl_arguments_url.curl_arguments_url import SwaggerRepo


ZSH_SCRIPT = """\
#compdef carl

_carl_test_completion() {
    local -a completions
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[carl] )) && return 1

    completions=("${(@f)$(carl utils zsh-completion "$CURRENT" "${words[*]}")}")

    if [ -n "completions" ]; then
        _describe -V unsorted completions -U
    fi
}

compdef _carl_test_completion carl;
"""

def main():
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
        elif generic_args.zsh_print_script:
            print(ZSH_SCRIPT)
        else:
            raise NotImplementedError()


if __name__ == '__main__':
    exit(main())
