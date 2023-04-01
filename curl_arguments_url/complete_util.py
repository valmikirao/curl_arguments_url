import argparse
import sys
from typing import cast, List

from curl_arguments_url.curl_arguments_url import SwaggerRepo, METHODS, get_param_values, GENERIC_ARGS


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='cmd')

    subparsers.add_parser('zsh-arguments-base-args')

    url_cmd = subparsers.add_parser('urls')
    url_cmd.add_argument('method', default='get', nargs='?', choices=METHODS, type=str.lower)
    url_cmd.add_argument('-f', '--format', default='{url}')

    url_cmd_zsh = subparsers.add_parser('zsh-describe-urls-args')
    url_cmd_zsh.add_argument('method', default='get', nargs='?', choices=METHODS, type=str.lower)

    params_cmd = subparsers.add_parser('params')
    params_cmd.add_argument('url')
    params_cmd.add_argument('-X', '--method', default='get', choices=METHODS, type=str.lower)
    params_cmd.add_argument('-f', '--format', default='{param}')

    params_cmd = subparsers.add_parser('zsh-arguments-params-args')
    params_cmd.add_argument('method')
    params_cmd.add_argument('url')

    param_vals_cmd = subparsers.add_parser('param-values')
    param_vals_cmd.add_argument('param-name')
    param_vals_cmd.add_argument('-f', '--format', default='{value}')

    args = parser.parse_args()

    method: str
    url: str
    param_name: str
    if args.cmd == 'zsh-arguments-base-args':
        sys.stdout.write(get_base_args())
    elif args.cmd == 'zsh-describe-urls-args':
        method = args.method
        sys.stdout.write(get_describe_url_args(method, swagger_model=SwaggerRepo()))
    elif args.cmd == 'zsh-arguments-params-args':
        url = args.url
        method = args.method
        sys.stdout.write(get_arguments_params_args(method, url, swagger_model=SwaggerRepo()))
    elif args.cmd == 'param-values':
        param_name = getattr(args, 'param-name')
        sys.stdout.write(get_param_values_str(param_name))
    else:
        raise NotImplementedError()

    return 0


def get_param_values_str(param_name: str) -> str:
    return_str = ''
    values_to_print = get_param_values(param_name)
    for val in values_to_print:
        return_str += f"{val}\n"

    return return_str


def get_arguments_params_args(method: str, url: str, swagger_model: SwaggerRepo) -> str:
    return_str = ''
    endpoint = swagger_model.get_endpoint_for_url(url, method)
    for param in endpoint.list_params():
        param_name = param.name
        description = param.description
        suffix = 'value:{{_carl_param_values ' + param_name + '}}'
        if description is not None:
            return_str += f"+{param_name}[{description}]:{suffix}\n"
        else:
            return_str += f"+{param_name}:{suffix}\n"

    return return_str


def get_describe_url_args(method: str, swagger_model: SwaggerRepo) -> str:
    return_str = ''
    swagger_urls = swagger_model.get_urls_for_method(method)
    for swagger_url in swagger_urls:
        url = swagger_url.url
        colon_escaped_url = url.replace(':', r'\:')
        description = swagger_url.description

        if description:
            return_str += f"{colon_escaped_url}:{description}\n"
        else:
            return_str += f"{colon_escaped_url}\n"

    return return_str


def get_base_args() -> str:
    return_str = ''
    for arg in GENERIC_ARGS:
        help_ = arg.kwargs['help']
        for name_or_flag in arg.name_or_flags:
            if arg.value_description is not None and 'choices' in arg.kwargs:
                choices = cast(List[str], arg.kwargs['choices'])
                choices_str = " ".join(choices)
                return_str += f"{name_or_flag}[{help_}]:{arg.value_description}:({choices_str})\n"
            elif arg.value_description is not None and 'choices' not in arg.kwargs:
                # deal with this when we actually have a default arg like this
                raise NotImplementedError()
            else:
                print(f"{name_or_flag}[{help_}]")
    return_str += '1:url:{_carl_url {url}}\n'
    return_str += '*::parameter:{_carl_params}\n'

    return return_str


if __name__ == '__main__':
    exit(main())
