import argparse

from curl_arguments_url.curl_arguments_url import SwaggerRepo, METHODS, ARG_CACHE
from diskcache import Cache


def main():
    swagger_model = SwaggerRepo()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='cmd')

    url_cmd = subparsers.add_parser('urls')
    url_cmd.add_argument('method', default='GET', nargs='?', choices=METHODS)

    params_cmd = subparsers.add_parser('params')
    params_cmd.add_argument('url')
    params_cmd.add_argument('-X', '--method', default='GET')
    params_cmd.add_argument('-f', '--format', default='{param}')

    param_vals_cmd = subparsers.add_parser('param-values')
    param_vals_cmd.add_argument('param-name')
    param_vals_cmd.add_argument('-f', '--format', default='{value}')

    args = parser.parse_args()

    if args.cmd == 'urls':
        endpoints = swagger_model.get_endpoints_for_method(args.method)
        for end in endpoints:
            print(end.url)
    elif args.cmd == 'params':
        endpoint = swagger_model.get_endpoint_for_url(args.url, args.method)
        for param in endpoint.list_params():
            print(args.format.format(
                param=param.name,
                # param_type=param.param_type,
            ))
    elif args.cmd == 'param-values':
        cache = Cache(ARG_CACHE)
        param_name = getattr(args, 'param-name')
        values = cache.get(param_name) or []
        for val in values:
            print(args.format.format(
                value=val
            ))

    return 0


if __name__ == '__main__':
    exit(main())
