import argparse
import shlex

from curl_arguments_url.curl_arguments_url import SwaggerRepo, METHODS, get_param_values


def main():
    swagger_model = SwaggerRepo()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='cmd')

    url_cmd = subparsers.add_parser('urls')
    url_cmd.add_argument('method', default='GET', nargs='?', choices=METHODS)
    url_cmd.add_argument('-f', '--format', default='{url}')

    params_cmd = subparsers.add_parser('params')
    params_cmd.add_argument('url')
    params_cmd.add_argument('-X', '--method', default='GET')
    params_cmd.add_argument('-f', '--format', default='{param}')

    param_vals_cmd = subparsers.add_parser('param-values')
    param_vals_cmd.add_argument('param-name')
    param_vals_cmd.add_argument('-f', '--format', default='{value}')

    args = parser.parse_args()

    if args.cmd == 'urls':
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
            print(format_template.format(
                param=param.name,
                quoted_param=shlex.quote(param.name),
                description=param.description
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
