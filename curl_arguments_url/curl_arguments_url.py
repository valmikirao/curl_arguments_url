"""Main module."""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, Callable, Any, \
    Set
from urllib.parse import urlencode
import traceback
from diskcache import Cache
import yaml

METHODS: List[str] = [
    'POST',
    'GET',
    'PUT',
    'DELETE',
    'PATCH'
]

T = TypeVar('T')
ArgType = Callable[[str], T]


class Raw(NamedTuple):
    value: str


class ArrayItem(NamedTuple):
    item: Any


def get_array_item_type(type_):
    def array_item_type(item: type_) -> ArrayItem:
        return ArrayItem(type_(item))

    return array_item_type


TYPES: Dict[str, ArgType] = {
    'string': str,
    'integer': int,
    'number': float,
    'boolean': lambda val: val == 'true',
}


class Param(NamedTuple, Generic[T]):
    name: str
    param_type: str
    description: str = ""
    required: bool = False
    type_: ArgType = str


EndpointParams = Dict[str, List[Param]]


class ParamArg(Generic[T]):
    """
    Makes it so you can have `+foo a +foo b` and `+foo a b`
    """

    param: Param
    values: List[T]

    def __init__(self, param: Param):
        self.param = param
        self.values = []

    def type_(self, val: str) -> 'ParamArg':
        self.values.append(self.param.type_(val))

        return self


class SwaggerModel(NamedTuple):
    id: str
    properties: List[Param]


class SwaggerEndpoint:
    params: EndpointParams
    path: str
    method: str

    @staticmethod
    def param_from_data(param_data: Dict[str, Any], swagger_models: Dict[str, SwaggerModel]) -> Iterable[Param]:
        if param_data.get('type', 'string') in TYPES:
            yield Param(
                name=param_data['name'],
                param_type=param_data['paramType'],
                description=param_data.get('description', ""),
                required=param_data.get('required', False),
                type_=TYPES[param_data.get('type', 'string')],
            )
        elif param_data['type'] in swagger_models:
            model = swagger_models[param_data['type']]
            for param in model.properties:
                yield Param(*param)
        else:
            # figure out how to warn for this
            yield Param(
                name=param_data['name'],
                param_type=param_data['paramType'],
                description=param_data.get('description', ""),
                required=param_data.get('required', False),
                type_=str,
            )

    def __init__(self, url: str, method: str, swagger_param_data: dict, swagger_models: Dict[str, SwaggerModel]):
        self.url = url
        self.method = method
        self.params = defaultdict(list)

        for param_data in swagger_param_data:
            for param in self.param_from_data(param_data, swagger_models):
                self.params[param.name].append(param)

        url_params = re.findall(r'\{(.*?)\}', url, re.DOTALL)
        for param_name in url_params:
            if param_name in self.params:
                pass
            else:
                # not sure how to warn about this yet
                # print(f"Warning: Parameter +{param_name} is in url but not explicitly declared", file=sys.stderr)
                self.params[param_name].append(Param(
                    name=param_name,
                    param_type='path'
                ))

    def list_params(self) -> Iterable[Param]:
        for param_list in self.params.values():
            for param in param_list:
                yield param


class SwaggerRepo:
    _endpoints: List[SwaggerEndpoint]

    @staticmethod
    def models_from_data(models_data: Dict[str, Any]) -> Dict[str, SwaggerModel]:
        return_models: Dict[str, SwaggerModel] = {}
        for name, spec in models_data.items():
            model = SwaggerModel(id=spec.get('id', name), properties=[])
            for prop_name, prop_spec in spec['properties'].items():
                type_str = prop_spec.get('type', 'string')

                def type_for_str(type_str_):
                    if type_str_ in TYPES:
                        return TYPES[type_str_]
                    else:
                        return Raw

                if type_str == 'array':
                    items_type_str = prop_spec.get('items', {}).get('type', 'string')
                    items_type = type_for_str(items_type_str)
                    type_ = get_array_item_type(items_type)
                else:
                    type_ = type_for_str(type_str)

                model.properties.append(Param(
                    name=prop_name,
                    param_type='json-post',
                    type_=type_,
                    required=prop_spec.get('required', False),
                    description=prop_spec.get('description', '')
                ))

                return_models[name] = model

        return return_models

    def __init__(self, swagger_data: Optional[dict] = None):
        self._endpoints = []
        if swagger_data is None:
            multi_swagger_data = []

            swagger_dir = os.path.join(os.environ['HOME'], '.carl', 'swagger')
            swagger_files = os.listdir(swagger_dir)
            for file in swagger_files:
                full_path = os.path.join(swagger_dir, file)
                with open(full_path, 'r') as fh:
                    multi_swagger_data.append(yaml.safe_load(fh))
        else:
            multi_swagger_data = [swagger_data]

        for swagger_data_ in multi_swagger_data:
            base_path = swagger_data_['basePath']
            self._models = self.models_from_data(swagger_data_['models'])
            for api in swagger_data_['apis']:
                endpoint_url = base_path + api['path']
                for op in api['operations']:
                    try:
                        method = op['method']
                        endpoint = SwaggerEndpoint(endpoint_url, method,
                                                   swagger_param_data=op['parameters'],
                                                   swagger_models=self._models)
                        self._endpoints.append(endpoint)
                    except Exception:
                        print(f"Error for {endpoint_url} {op.get('method', '<no method>')}", file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)

    def get_endpoint_for_url(self, url: str, method: str = 'GET') -> SwaggerEndpoint:
        for endpoint in self._endpoints:
            if url == endpoint.url and method == endpoint.method:
                return endpoint
        else:
            raise Exception(f"Endpoint doesn't exist: {url} {method}")

    def get_endpoints_for_method(self, method: str) -> Iterable[SwaggerEndpoint]:
        for endpoint in self._endpoints:
            if method == endpoint.method:
                yield endpoint


def cli_args_to_cmd(cli_args: Sequence[str], swagger_model: Optional[SwaggerRepo] = None)\
      -> Tuple[Sequence[str], argparse.Namespace]:
    generic_args, remaining_args = parse_generic_args(cli_args)

    if swagger_model is None:
        swagger_model = SwaggerRepo()

    endpoint = swagger_model.get_endpoint_for_url(generic_args.url, generic_args.method)

    param_args, remaining_curl_args = parse_param_args(endpoint, remaining_args)

    url_template = generic_args.url

    param_args = param_args_to_pairs(param_args)
    cache_param_arg_pairs(param_args)
    headers, param_args = format_headers(param_args, endpoint.params)
    post_data, param_args = format_post_data(param_args, endpoint.params)
    url = format_url(url_template, param_args)

    return ['curl', '-X', generic_args.method, url, *headers, *post_data, *remaining_curl_args], generic_args


ArgValue = Union[str, int, float]
ArgPairs = List[Tuple[str, ArgValue]]

MAX_HISTORY = 200

ARG_CACHE = os.path.join(os.environ["HOME"], '.carl', 'arg_cache')


def cache_param_arg_pairs(param_args: ArgPairs) -> None:
    cache = Cache(ARG_CACHE)
    for key, value in param_args:
        arg_history: List[ArgValue] = cache.get(key) or []
        new_history: List[ArgValue] = [value] + [a for a in arg_history if a != value]
        new_history = new_history[:MAX_HISTORY]
        cache.set(key, new_history)


def format_post_data(param_args: ArgPairs, endpoint_params: EndpointParams) -> Tuple[List[str], ArgPairs]:
    remaining_argpairs: ArgPairs = []
    post_data: Dict[str, Any] = {}

    for arg_name, arg_value in param_args:
        for param in endpoint_params[arg_name]:
            if param.param_type == 'json-post':
                def process_raws(arg_value_):
                    if isinstance(arg_value_, Raw):
                        try:
                            return json.loads(arg_value_.value)
                        except json.decoder.JSONDecodeError:
                            raise Exception('Unimplemeted')
                    else:
                        return arg_value_

                if isinstance(arg_value, ArrayItem):
                    if arg_name not in post_data:
                        post_data[arg_name] = [process_raws(arg_value.item)]
                    else:
                        post_data[arg_name].append(process_raws(arg_value.item))
                else:
                    post_data[arg_name] = process_raws(arg_value)
                break
        else:
            remaining_argpairs.append((arg_name, arg_value),)

    if post_data:
        formatted_postdata = ['-H', 'Content-Type: application/json', '--data-binary', json.dumps(post_data)]
    else:
        formatted_postdata = []

    return formatted_postdata, remaining_argpairs


def format_headers(param_args: ArgPairs, endpoint_params: EndpointParams) -> Tuple[List[str], ArgPairs]:
    remaining_argpairs: ArgPairs = []
    headers: List[str] = []
    for arg_name, arg_value in param_args:
        for param in endpoint_params[arg_name]:
            if param.param_type == 'header':
                headers.extend(['-H', f"{param.name}: {arg_value}"])
                break
        else:
            remaining_argpairs.append((arg_name, arg_value),)

    return headers, remaining_argpairs


def format_url(url_template: str, param_args: ArgPairs) -> str:
    query_args: ArgPairs = []
    returned_url = url_template

    for arg_name, arg_value in param_args:
        matched = False
        def replace_url_param(_):
            nonlocal matched
            matched = True
            return arg_value

        returned_url = re.sub(r'\{%s\}' % arg_name, replace_url_param, returned_url)

        if not matched:
            query_args.append((arg_name, arg_value),)

    if query_args:
        returned_url += '?' + urlencode(query_args)

    return returned_url


def param_args_to_pairs(param_args: argparse.Namespace) -> ArgPairs:
    args_pairs: ArgPairs = []
    param_values: List[ParamArg]
    for _, param_values in param_args.__dict__.items():
        if param_values and len(param_values) and len(param_values[0].values):
            key = param_values[0].param.name  # this is the true name, without argparse munging
            for val in param_values[0].values:  # using values[0] because of ParamArg weirdness
                args_pairs.append((key, val),)

    return args_pairs


def parse_param_args(endpoint: SwaggerEndpoint, remaining_args: Sequence[str]) \
      -> Tuple[argparse.Namespace, Sequence[str]]:
    """
    Note: this is a very crude approximation of the swagger param model.
    See https://swagger.io/docs/specification/describing-parameters/ for what the possibilities really are
    """
    parser = argparse.ArgumentParser(prefix_chars='-+')
    arg_deduper: Set[str] = set()

    parser = add_args_from_params(parser, endpoint, arg_deduper)
    param_args, still_remaining_args = parser.parse_known_args(remaining_args)

    curl_parser = argparse.ArgumentParser()
    curl_parser.add_argument('remaining', nargs='*')
    remaining_curl_args = curl_parser.parse_args(still_remaining_args).remaining

    return param_args, remaining_curl_args


def add_args_from_params(parser: argparse.ArgumentParser, endpoint: SwaggerEndpoint, arg_deduper: Set[str]) \
      -> argparse.ArgumentParser:
    for param in endpoint.list_params():
        if param.name in arg_deduper:
            print(f"Warning: Parameter +{param.name} appears twice", file=sys.stderr)
        else:
            arg_deduper.add(param.name)
            parser.add_argument(f"+{param.name}", type=ParamArg(param).type_, required=param.required, nargs="+")

    return parser


def parse_generic_args(cli_args: Sequence[str]) -> Tuple[argparse.Namespace, Sequence[str]]:
    parser = argparse.ArgumentParser(prefix_chars='-+')
    parser.add_argument('url')
    parser.add_argument('-X', '--method', choices=METHODS, default='GET')
    parser.add_argument('-p', '--print-cmd', action='store_true', default=False)
    parser.add_argument('-n', '--no-run-cmd', action='store_false', dest='run_cmd', default=True)
    generic_args, remaining_args = parser.parse_known_args(cli_args)

    return generic_args, remaining_args
