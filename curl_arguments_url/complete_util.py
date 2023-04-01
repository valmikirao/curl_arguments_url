import argparse
import shlex
from typing import cast, List

from curl_arguments_url.curl_arguments_url import SwaggerRepo, METHODS, get_param_values, GENERIC_ARGS


def main():
    swagger_model = SwaggerRepo()

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

    if args.cmd == 'zsh-arguments-base-args':
        for arg in GENERIC_ARGS:
            help_ = arg.kwargs['help']
            for name_or_flag in arg.name_or_flags:
                if arg.value_description is not None and 'choices' in arg.kwargs:
                    choices = cast(List[str], arg.kwargs['choices'])
                    choices_str = " ".join(choices)
                    print(f"{name_or_flag}[{help_}]:{arg.value_description}:({choices_str})")
                elif arg.value_description is not None and 'choices' not in arg.kwargs:
                    # deal with this when we actually have a default arg like this
                    raise NotImplementedError()
                else:
                    print(f"{name_or_flag}[{help_}]")

        print('1:url:{_carl_url}')
        print('*::parameter:{_carl_params}')

    elif args.cmd == 'zsh-describe-urls-args':
        swagger_urls = swagger_model.get_urls_for_method(args.method)
        for swagger_url in swagger_urls:
            url = swagger_url.url
            colon_escaped_url = url.replace(':', r'\:')
            summary = swagger_url.summary

            if summary:
                print(f"{colon_escaped_url}:{summary}")
            else:
                print(colon_escaped_url)
    elif args.cmd == 'zsh-arguments-params-args':
        endpoint = swagger_model.get_endpoint_for_url(args.url, args.method.lower())
        for param in endpoint.list_params():
            param_name = param.name
            description = param.description
            if description is not None:
                print(f"+{param_name}[{description}]:" + r'value:{{_carl_param_values {param}}}')
            else:
                print(f"+{param_name}:" + r'value:{{_carl_param_values {param}}}')
    elif args.cmd == 'urls':
        swagger_urls = swagger_model.get_urls_for_method(args.method)
        format_template = args.format
        for swagger_url in swagger_urls:
            url = swagger_url.url
            colon_escaped_url = url.replace(':', r'\:')
            summary = swagger_url.summary
            print(format_template.format(
                url=url, colon_escaped_url=colon_escaped_url, summary=summary
            ))
    elif args.cmd == 'params':
        endpoint = swagger_model.get_endpoint_for_url(args.url, args.method)
        format_template = args.format
        for param in endpoint.list_params():
            if param.description is not None:
                description = param.description
            else:
                description = ''

            print(format_template.format(
                param=param.name,
                quoted_param=shlex.quote(param.name),
                description=description
                # param_type=param.param_type,
            ))
    elif args.cmd == 'param-values':
        param_name = getattr(args, 'param-name')
        values_to_print = get_param_values(param_name)
        format_template = args.format
        for val in values_to_print:
            print(format_template.format(
                value=val,
                quoted_value=shlex.quote(val)
            ))

    return 0


if __name__ == '__main__':
    exit(main())
