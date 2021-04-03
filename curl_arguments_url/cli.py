"""Console script for curl_arguments_url."""
import sys
import shlex
import subprocess

from curl_arguments_url.curl_arguments_url import cli_args_to_cmd


def main():
    """Console script for curl_arguments_url."""

    cmd, generic_args = cli_args_to_cmd(sys.argv[1:])

    if generic_args.print_cmd:
        print(" ".join(shlex.quote(a) for a in cmd))

    try:
        if generic_args.run_cmd:
            subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        return e.returncode
    else:
        return 0


if __name__ == '__main__':
    exit(main())


