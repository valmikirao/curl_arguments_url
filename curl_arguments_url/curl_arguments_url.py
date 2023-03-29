"""Main module."""
import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from hashlib import md5
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, Callable, Any, \
    Set, MutableMapping, cast
from typing_extensions import Literal
from urllib.parse import urlencode

import click
import yaml

CARL_DIR = os.path.join(os.environ["HOME"], '.carl')

METHODS: List[str] = [
    'POST',
    'GET',
    'PUT',
    'DELETE',
    'PATCH'
]

T = TypeVar('T')
V = TypeVar('V')
U = TypeVar('U')
ArgType = Callable[[str], T]


class FileCache(Generic[T, V]):
    CACHE_DIR = os.path.join(CARL_DIR, 'cache')

    def __init__(self, dir: str):
        self._dir = os.path.join(self.CACHE_DIR, dir)

    def clear(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _get_key_filename(self, key: T) -> str:
        key_stringified = json.dumps(key).encode()
        key_hash = md5(key_stringified).hexdigest()
        return os.path.join(self._dir, key_hash)

    def __getitem__(self, key: T) -> V:
        key_filename = self._get_key_filename(key)
        if os.path.exists(key_filename):
            with open(key_filename, 'r') as fh:
                return json.load(fh)
        else:
            raise KeyError(key)

    def __setitem__(self, key: T, value: V) -> None:
        os.makedirs(self._dir, exist_ok=True)
        key_filename = self._get_key_filename(key)
        with open(key_filename, 'w') as fh:
            json.dump(value, fh)

    def get(self, key: T, default: V) -> V:
        # made default required on purpose here
        try:
            return self[key]
        except KeyError:
            return default


class Raw(NamedTuple):
    value: str


class ArrayItem(NamedTuple):
    item: Any


class ArrayItemType(NamedTuple):
    type_: Callable[[Any], Any]

    def __call__(self, item: str) -> ArrayItem:
        return ArrayItem(self.type_(item))


def boolean_type(val: Optional[str]) -> bool:
    if val and val.lower() in ('1', 't', 'true'):
        return True
    elif val is None or val.lower() in ('', '0', 'f', 'false'):
        return False
    else:
        raise TypeError(f"Value {val!r} can't be converted to boolean")


TYPES: Dict[str, ArgType] = {
    'string': str,
    'integer': int,
    'number': float,
    'boolean': boolean_type,
}


class Param(NamedTuple):
    name: str
    param_type: str
    description: str = ''
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


class SwaggerUrl(NamedTuple):
    url: str
    summary: Optional[str]


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
                description=param_data.get('description', ''),
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
                    type_ = ArrayItemType(items_type)
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

    _endpoint_by_method_url_cache: FileCache[Tuple[str, str], Dict[str, Any]]
    _url_by_method_cache: FileCache[str, List[SwaggerUrl]]
    _time_cache: FileCache[Literal['TIME'], float]

    def __init__(self, swagger_test_data: Optional[dict] = None):
        # self._endpoints = []
        self._endpoint_by_method_url_cache = FileCache('endpoint_by_method_url_cache')
        self._url_by_method_cache = FileCache('url_by_method_cache')
        self._time_cache = FileCache('time_cache')

        if swagger_test_data is None:
            swagger_dir = os.path.join(os.environ['HOME'], '.carl', 'swagger')
            swagger_files = [os.path.join(swagger_dir, f) for f in os.listdir(swagger_dir)]

            cache_time = self._time_cache.get('TIME', 0)
            yaml_files_time = max(os.path.getmtime(f) for f in swagger_files)
            if yaml_files_time > cache_time:
                self.clear_all_caches()
                self._load_swagger_data(swagger_files=swagger_files)
                self._time_cache['TIME'] = datetime.now().timestamp()
        else:
            # this is a testing case, so make all caches are ephemeral
            self._endpoint_by_method_url_cache = cast(FileCache, {})
            self._url_by_method_cache = cast(FileCache, {})
            self._time_cache = cast(FileCache, {})

            self._load_swagger_data(swagger_data=swagger_test_data)

    def clear_all_caches(self) -> None:
        self._endpoint_by_method_url_cache.clear()
        self._url_by_method_cache.clear()
        self._time_cache.clear()

    def _load_swagger_data(self, swagger_files: Optional[Iterable[str]] = None,
                           swagger_data: Optional[Dict[str, Any]] = None):
        multi_swagger_data: List[Dict[str, Any]] = []
        if swagger_files is not None:
            for file in swagger_files:
                with open(file, 'r') as fh:
                    loaded = yaml.safe_load(fh)
                    if loaded is not None:
                        multi_swagger_data.append(loaded)
                    else:
                        raise Exception(f"Issue with Swagger file {file!r}")
        elif swagger_data is not None:
            multi_swagger_data = [swagger_data]
        else:
            raise Exception(f"One of 'swagger_files' or 'swagger_data' is required")
        urls_by_method: MutableMapping[str, List[SwaggerUrl]] = defaultdict(list)
        for swagger_data_ in multi_swagger_data:
            base_path = swagger_data_['basePath']
            if 'models' in swagger_data_:
                models_data = swagger_data_['models']
            else:
                models_data = {}
            for api in swagger_data_['apis']:
                endpoint_url = base_path + api['path']
                for op in api['operations']:
                    method = op['method']
                    parameters = op['parameters']
                    summary: Optional[str] = op.get('summary')
                    swagger_endpoint_dict = {
                        'url': endpoint_url, 'method': method,
                        'swagger_param_data': parameters, 'swagger_models_data': models_data,
                    }
                    self._endpoint_by_method_url_cache[method, endpoint_url] = swagger_endpoint_dict
                    urls_by_method[op['method']].append(SwaggerUrl(
                        url=endpoint_url,
                        summary=summary
                    ))

            for method, urls in urls_by_method.items():
                self._url_by_method_cache[method] = urls

    def get_endpoint_for_url(self, url: str, method: str = 'GET') -> SwaggerEndpoint:
        swagger_endpoint_dict = self._endpoint_by_method_url_cache[method, url]
        swagger_models = self.models_from_data(swagger_endpoint_dict['swagger_models_data'])
        return SwaggerEndpoint(
            url=swagger_endpoint_dict['url'],
            method=swagger_endpoint_dict['method'],
            swagger_param_data=swagger_endpoint_dict['swagger_param_data'],
            swagger_models=swagger_models
        )

    def get_urls_for_method(self, method: str) -> Iterable[SwaggerUrl]:
        for item in self._url_by_method_cache.get(method, []):
            yield SwaggerUrl(*item)


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

arg_cache = FileCache('args')


def cache_param_arg_pairs(param_args: ArgPairs) -> None:
    for key, value in param_args:
        arg_history: List[ArgValue] = arg_cache.get(key, [])
        new_history: List[ArgValue] = [value] + [a for a in arg_history if a != value]
        new_history = new_history[:MAX_HISTORY]
        arg_cache[key] = new_history


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
            return str(arg_value)

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
    @click.command()
    @click.argument('url')
    @click.option('-X', '--method', type=click.Choice(METHODS), default='GET')
    @click.option('-p', '--print-cmd', is_flag=True, default=False)
    @click.option('-n', '--no-run-cmd', is_flag=True, default=True, help='Do not execute the command')
    def parse_generic_args(url: str, method: str, print_cmd: bool, no_run_cmd: bool):
        """Parses generic arguments for HTTP requests"""
        generic_args = (url, method, print_cmd, no_run_cmd)
        return generic_args
    parser = argparse.ArgumentParser(prefix_chars='-+')
    parser.add_argument('url')
    parser.add_argument('-X', '--method', choices=METHODS, default='GET')
    parser.add_argument('-p', '--print-cmd', action='store_true', default=False)
    parser.add_argument('-n', '--no-run-cmd', action='store_false', dest='run_cmd', default=True)
    generic_args, remaining_args = parser.parse_known_args(cli_args)

    return generic_args, remaining_args


def get_param_values(param_name: str) -> Iterable[str]:
    values = arg_cache.get(param_name, [])
    dedupe = set()

    for sub_values in values:
        if isinstance(sub_values, str):
            sub_values = [sub_values]

        for val in sub_values:
            if val not in dedupe and val != '':
                yield val
                dedupe.add(val)
