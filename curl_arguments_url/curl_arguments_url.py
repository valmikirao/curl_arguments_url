"""Main module."""
import argparse
import json
import os
import re
import shutil
import sys
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from enum import Enum
from hashlib import md5
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, Callable, Any, \
    Set, MutableMapping, cast, Type

from jsonref import replace_refs as replace_json_refs  # type: ignore
from openapi_schema_pydantic import OpenAPI, Operation, RequestBody, Schema, Reference, Parameter
from pydantic import BaseModel, validator
from typing_extensions import Literal
from urllib.parse import urlencode

import yaml

REMAINING_ARG = 'passed_to_curl'

CARL_DIR = os.path.join(os.environ["HOME"], '.carl')
SWAGGER_DIR = os.environ.get(
    'CARL_SWAGGER_DIR',
    os.path.join(CARL_DIR, 'swagger')
)

METHODS: List[str] = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace']


T = TypeVar('T')
V = TypeVar('V')
U = TypeVar('U')
ArgType = Callable[[str], T]


class FileCache(ABC, Generic[T, V]):
    CACHE_DIR = os.path.join(CARL_DIR, 'cache')

    def __init__(self, dir: str):
        self._dir = os.path.join(self.CACHE_DIR, dir)

    @abstractmethod
    def freeze(self, value: V) -> str:
        ...


    @abstractmethod
    def thaw(self, frozen_value: str) -> V:
        ...

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
                return self.thaw(fh.read())
        else:
            raise KeyError(key)

    def __setitem__(self, key: T, value: V) -> None:
        os.makedirs(self._dir, exist_ok=True)
        key_filename = self._get_key_filename(key)
        frozen_value = self.freeze(value)
        with open(key_filename, 'w') as fh:
            fh.write(frozen_value)

    def get(self, key: T, default: V) -> V:
        # made default required on purpose here
        try:
            return self[key]
        except KeyError:
            return default


class FileCacheJson(FileCache[T, V]):
    def freeze(self, value: V) -> str:
        return json.dumps(value)

    def thaw(self, frozen_value: str) -> V:
        return json.loads(frozen_value)


class FileCachePydantic(FileCache[T, V]):
    def __init__(self, dir: str, model: Type[V]):
        super().__init__(dir)
        # TODO: Is there a better way to do this?
        assert issubclass(model, BaseModel)
        self._model = model

    def freeze(self, value: V) -> str:
        # TODO: Is there a better way to do this than cast()?
        return cast(BaseModel, value).json()

    def thaw(self, frozen_value: str) -> V:
        # TODO: Is there a better way to do this than cast()?
        return cast(V, cast(BaseModel, self._model).parse_raw(frozen_value))


def boolean_type(val: Optional[str]) -> bool:
    if val and val.lower() in ('1', 't', 'true'):
        return True
    elif val is None or val.lower() in ('', '0', 'f', 'false'):
        return False
    else:
        raise TypeError(f"Value {val!r} can't be converted to boolean")


class SpecialSwaggerTypeStrs:
    object = 'object'
    array = 'array'


class ArgTypeEnum(Enum):
    string = 'string'
    integer = 'integer'
    number = 'number'
    boolean = 'boolean'
    json = 'json'


class ArgTypeModel(BaseModel):
    type_: ArgTypeEnum
    is_array: bool = False

    def converter(self, value: str) -> Any:
        return ARG_TYPE_FUNCS[self.type_](value)


ARG_TYPE_FUNCS: Dict[ArgTypeEnum, ArgType] = {
    ArgTypeEnum.string: str,
    ArgTypeEnum.integer: int,
    ArgTypeEnum.number: float,
    ArgTypeEnum.boolean: boolean_type,
    ArgTypeEnum.json: json.loads
}


class ParamType(Enum):
    query = 'query'
    path = 'path'
    header = 'header'
    json_body = 'json_body'


class CarlParam(BaseModel):
    name: str
    param_type: ParamType
    description: Optional[str] = None
    required_: bool = False
    type_: ArgTypeModel = ArgTypeModel(type_=ArgTypeEnum.string)

    @validator('required_', pre=True)
    def required(cls, v: Any) -> bool:
        return bool(v)


EndpointParams = Dict[str, List[CarlParam]]


class ParamArg(Generic[T]):
    """
    Makes it so you can have `+foo a +foo b` and `+foo a b`
    """

    param: CarlParam
    values: List[T]

    def __init__(self, param: CarlParam):
        self.param = param
        self.values = []

    def type_(self, val: str) -> 'ParamArg':
        self.values.append(self.param.type_.converter(val))

        return self


class SwaggerModel(NamedTuple):
    id: str
    properties: List[CarlParam]


class SwaggerUrl(NamedTuple):
    url: str
    description: Optional[str]


class EndpointToCache(BaseModel):
    endpoint_url: str
    method: str
    parameters: List[CarlParam]


class SwaggerEndpoint:
    params: EndpointParams
    path: str
    method: str

    def __init__(self, url: str, method: str, parameters: List[CarlParam]):
        self.url = url
        self.method = method
        self.params: EndpointParams = defaultdict(list)

        for param in parameters:
            self.params[param.name].append(param)

        url_params = re.findall(r'\{(.*?)\}', url, re.DOTALL)
        for param_name in url_params:
            if param_name in self.params:
                pass
            else:
                # not sure how to warn about this yet
                # print(f"Warning: Parameter +{param_name} is in url but not explicitly declared", file=sys.stderr)
                self.params[param_name].append(CarlParam(
                    name=param_name,
                    param_type=ParamType.path
                ))

    def list_params(self) -> Iterable[CarlParam]:
        for param_list in self.params.values():
            for param in param_list:
                yield param


DISPLAY_DESCRIPTION_IDEAL_LENGTH = 100

def get_displayed_description(description: Optional[str], summary: Optional[str]) -> Optional[str]:
    def _ranker(candidate: Optional[str]) -> Tuple[int, int]:
        if candidate is None or candidate == '':
            # discard those that don't exist
            return 0, 0
        elif len(candidate) <= DISPLAY_DESCRIPTION_IDEAL_LENGTH:
            # the longest one under X chars
            return 2, len(candidate)
        else:
            # the shortest one above X chars
            return 1, -len(candidate)

    return_val: Optional[str] = None
    current_max_rank = (0, 0)
    for val in (description, summary):
        val_rank = _ranker(val)
        if val_rank > current_max_rank:
            return_val = val
            current_max_rank = val_rank

    return return_val



class SwaggerRepo:

    _endpoint_by_method_url_cache: FileCache[Tuple[str, str], EndpointToCache]
    _url_by_method_cache: FileCache[str, List[SwaggerUrl]]
    _time_cache: FileCache[Literal['TIME'], float]

    def __init__(self, files: Optional[List[str]] = None, ephemeral: bool = False):
        if not ephemeral:
            self._endpoint_by_method_url_cache = FileCachePydantic('endpoint_by_method_url_cache', EndpointToCache)
            self._url_by_method_cache = FileCacheJson('url_by_method_cache')
            self._time_cache = FileCacheJson('time_cache')
        else:
            # this is a testing case, so make all caches are ephemeral
            # TODO: we should probably be caching to a temp dir instead of ephemera for testing
            self._endpoint_by_method_url_cache = cast(FileCache, {})
            self._url_by_method_cache = cast(FileCache, {})
            self._time_cache = cast(FileCache, {})

        if files is None:
            swagger_files = [os.path.join(SWAGGER_DIR, f) for f in os.listdir(SWAGGER_DIR)]
        else:
            swagger_files = files

        cache_time = self._time_cache.get('TIME', 0)
        yaml_files_time = max(os.path.getmtime(f) for f in swagger_files)
        if yaml_files_time > cache_time:
            self.clear_all_caches()
            self._load_swagger_data(swagger_files=swagger_files)
            self._time_cache['TIME'] = datetime.now().timestamp()

    def clear_all_caches(self) -> None:
        self._endpoint_by_method_url_cache.clear()
        self._url_by_method_cache.clear()
        self._time_cache.clear()

    def _load_swagger_data(self, swagger_files: Optional[Iterable[str]]):
        multi_swagger_data: List[OpenAPI] = []
        if swagger_files is not None:
            for file in swagger_files:
                with open(file, 'r') as fh:
                    loaded = yaml.safe_load(fh)
                    if loaded is not None:
                        loaded = replace_json_refs(loaded, merge_props=True)
                        multi_swagger_data.append(OpenAPI.parse_obj(loaded))
                    else:
                        # At certain times we should fail more loudly here
                        pass

        urls_by_method: MutableMapping[str, List[SwaggerUrl]] = defaultdict(list)
        for swagger_data_ in multi_swagger_data:
            if swagger_data_.paths:
                server_urls = [s.url for s in swagger_data_.servers]
                for path_str, path_spec in swagger_data_.paths.items():
                    # Note: this doesn't deal with relative servers, we might need to deal with that
                    # when fetching the spec
                    if path_spec.servers:
                        server_urls_for_path = [s.url for s in swagger_data_.servers]
                    else:
                        server_urls_for_path = server_urls

                    path_description = get_displayed_description(
                        description=path_spec.description,
                        summary=path_spec.summary
                    )

                    for method in METHODS:
                        operation: Optional[Operation] = getattr(path_spec, method)
                        if operation:
                            parameters: List[CarlParam] = []
                            for parameter in operation.parameters or []:
                                if isinstance(parameter, Parameter):
                                    param_type = self.schema_to_arg_type(parameter.param_schema)
                                    parameters.append(CarlParam(
                                        name=parameter.name,
                                        param_type=ParamType(parameter.param_in),
                                        description=parameter.description,
                                        required_=parameter.required,
                                        type_=param_type
                                    ))
                                else:  # is a Reference
                                    # Hopefully we have already resolved the references
                                    pass
                            if isinstance(operation.requestBody, RequestBody):
                                params_from_body = self._get_params_from_body(operation.requestBody)
                                parameters.extend(params_from_body)

                            for server_url in server_urls_for_path:
                                endpoint_url = server_url + path_str
                                self._endpoint_by_method_url_cache[method, endpoint_url] = EndpointToCache(
                                    endpoint_url=endpoint_url,
                                    method=method,
                                    parameters=parameters
                                )

                                op_description = get_displayed_description(
                                    description=operation.description,
                                    summary=operation.summary
                                )
                                if op_description is None or op_description == '':
                                    op_description = path_description

                                urls_by_method[method].append(SwaggerUrl(
                                    url=endpoint_url,
                                    description=op_description
                                ))

        for method, urls in urls_by_method.items():
            self._url_by_method_cache[method] = urls

    @staticmethod
    def schema_to_arg_type(schema: Union[Schema, Reference, None]) -> ArgTypeModel:
        if schema is None or isinstance(schema, Reference):
            return ArgTypeModel(type_=ArgTypeEnum.string)
        schema_type = schema.type
        schema_items = schema.items
        if schema_type is None or schema_type == []:
            # default
            return ArgTypeModel(type_=ArgTypeEnum.string)
        else:
            schema_type_: str
            if isinstance(schema_type, List):
                # don't know how to handle multiple types yet
                schema_type_ = schema_type[0]
            else:
                schema_type_ = schema_type

            if schema_type_ == SpecialSwaggerTypeStrs.object:
                return ArgTypeModel(type_=ArgTypeEnum.json)
            elif schema_type_ == SpecialSwaggerTypeStrs.array:
                if schema_items is None or isinstance(schema_items, Reference):
                    return ArgTypeModel(type_=ArgTypeEnum.string, is_array=True)
                else:
                    items_type = SwaggerRepo.schema_to_arg_type(Schema(
                        type=schema_items.type,
                        items=None
                    ))
                    if items_type.is_array:
                        return ArgTypeModel(
                            type_=ArgTypeEnum.json,
                            is_array=True
                        )
                    else:
                        return ArgTypeModel(
                            type_=items_type.type_,
                            is_array=True
                        )
            else:
                arg_type_enum = ArgTypeEnum(schema_type_)
                return ArgTypeModel(
                    type_=arg_type_enum,
                    is_array=False
                )

    def _get_params_from_body(self, request_body: RequestBody) -> Iterable[CarlParam]:
        for json_mime_type in ('application/json', 'json'):
            if json_mime_type in request_body.content:
                schema = request_body.content[json_mime_type].media_type_schema
                if isinstance(schema, Schema) and schema.type == SpecialSwaggerTypeStrs.object and schema.properties:
                    if schema.required is not None:
                        required_props = set(schema.required)
                    else:
                        required_props = set()
                    for prop_name, prop_schema in schema.properties.items():
                        carl_param_type = self.schema_to_arg_type(prop_schema)
                        if isinstance(prop_schema, Schema):
                            description = prop_schema.description
                        else:
                            description = None

                        yield CarlParam(
                            name=prop_name,
                            param_type=ParamType.json_body,
                            description=description,
                            required_=(prop_name in required_props),
                            type_=carl_param_type
                        )
                else:
                    # Can't handle these yet
                    pass
            else:
                # Can't handle anything else yet
                pass

    def get_endpoint_for_url(self, url: str, method: str = 'GET') -> SwaggerEndpoint:
        swagger_endpoint_cached = self._endpoint_by_method_url_cache[method, url]
        return SwaggerEndpoint(
            url=swagger_endpoint_cached.endpoint_url,
            method=swagger_endpoint_cached.method,
            parameters=swagger_endpoint_cached.parameters
        )

    def get_urls_for_method(self, method: str) -> Iterable[SwaggerUrl]:
        for item in self._url_by_method_cache.get(method.lower(), []):
            yield SwaggerUrl(*item)


class GenericArgs(NamedTuple):
    print_cmd: bool
    run_cmd: bool


def cli_args_to_cmd(cli_args: Sequence[str], swagger_model: Optional[SwaggerRepo] = None)\
      -> Tuple[Sequence[str], GenericArgs]:
    initial_parser = argparse.ArgumentParser(add_help=False)
    initial_parser.add_argument('url', nargs="?")
    initial_parser.add_argument('-h', '--help', action='store_true')
    initial_parser = add_generic_args(initial_parser)

    initial_args, _ = initial_parser.parse_known_args(cli_args)
    if initial_args.url is None:
        # Asked for help, but no url, or just forgot the url, so this should print the correct help/error message
        help_out_parser = argparse.ArgumentParser(add_help=True)
        help_out_parser.add_argument('url')
        help_out_parser = add_generic_args(help_out_parser)
        help_out_parser.parse_args(cli_args)

        raise AssertionError('We should not get here, the above .parse_args() should print help and exit')

    method: str = initial_args.method.lower()

    if swagger_model is None:
        swagger_model = SwaggerRepo()

    correct_url_parser = argparse.ArgumentParser(add_help=False)
    possible_urls = [u.url for u in swagger_model.get_urls_for_method(method)]
    correct_url_parser.add_argument('url', choices=possible_urls)
    correct_url_parser = add_generic_args(correct_url_parser)
    # this sees if the url supplied makes sense, and prints correct error if it doesn't
    correct_url_parser.parse_known_args(cli_args)

    url_template: str = initial_args.url
    full_parser = argparse.ArgumentParser(add_help=True,)
    full_parser = add_generic_args(full_parser)
    url_subparser = full_parser.add_subparsers(dest='url')
    given_url_subparser = url_subparser.add_parser(url_template,  prefix_chars='-+')

    endpoint = swagger_model.get_endpoint_for_url(url_template, method)
    given_url_subparser = add_args_from_params(given_url_subparser, endpoint)
    given_url_subparser.add_argument(REMAINING_ARG, nargs='*')

    args = full_parser.parse_args(cli_args)
    remaining: List[str] = args.__dict__.pop(REMAINING_ARG, [])
    param_arg_pairs = param_args_to_pairs(args)

    cache_param_arg_pairs(param_arg_pairs)
    headers, param_arg_pairs = format_headers(param_arg_pairs, endpoint.params)
    post_data, param_arg_pairs = format_post_data(param_arg_pairs, endpoint.params)
    url = format_url(url_template, param_arg_pairs)

    method_: str = args.method.upper()

    generic_args = GenericArgs(
        print_cmd=args.print_cmd,
        run_cmd=args.run_cmd
    )

    return ['curl', '-X', method_, url, *headers, *post_data, *remaining], generic_args


ArgValue = Union[str, int, float, Dict[str, 'ArgValue'], List['ArgValue']]
ArgPairs = List[Tuple[str, ArgValue]]

MAX_HISTORY = 200

arg_cache: FileCacheJson = FileCacheJson('args')


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
            if param.param_type == ParamType.json_body:
                if param.type_.is_array:
                    if arg_name not in post_data:
                        post_data[arg_name] = [arg_value]
                    else:
                        post_data[arg_name].append(arg_value)
                else:
                    post_data[arg_name] = arg_value
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
            if param.param_type == ParamType.header:
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
    param_values: List[Any]
    for _, param_values in param_args.__dict__.items():
        if isinstance(param_values, List) and len(param_values) >= 1:
            param_value = param_values[0]  # using values[0] because of ParamArg weirdness
        else:
            param_value = param_values
        if isinstance(param_value, ParamArg) and len(param_value.values):
            key = param_value.param.name  # this is the true name, without argparse munging
            for val in param_value.values:
                args_pairs.append((key, val),)

    return args_pairs


def parse_param_args(endpoint: SwaggerEndpoint, remaining_args: Sequence[str]) \
      -> Tuple[argparse.Namespace, Sequence[str]]:
    """
    Note: this is a very crude approximation of the swagger param model.
    See https://swagger.io/docs/specification/describing-parameters/ for what the possibilities really are
    """
    parser = argparse.ArgumentParser(prefix_chars='-+')

    parser = add_args_from_params(parser, endpoint)
    param_args, still_remaining_args = parser.parse_known_args(remaining_args)

    curl_parser = argparse.ArgumentParser()
    curl_parser.add_argument('remaining', nargs='*')
    remaining_curl_args = curl_parser.parse_args(still_remaining_args).remaining

    return param_args, remaining_curl_args


def add_args_from_params(parser: argparse.ArgumentParser, endpoint: SwaggerEndpoint) \
      -> argparse.ArgumentParser:
    arg_deduper: Set[str] = set()
    for param in endpoint.list_params():
        if param.name in arg_deduper:
            print(f"Warning: Parameter +{param.name} appears twice", file=sys.stderr)
        else:
            arg_deduper.add(param.name)
            nargs: Union[int, Literal['+']] = '+' if param.type_.is_array else 1
            parser.add_argument(f"+{param.name}", type=ParamArg(param).type_, required=param.required_, nargs=nargs,
                                help=param.description)

    return parser


ArgParserArgAction = Literal['store_true', 'store_false']  # will add other actions as needed


class ArgParserArg(NamedTuple):
    name_or_flags: List[str]
    kwargs: Dict[str, Any]
    value_description: Optional[str] = None


GENERIC_ARGS = [
    ArgParserArg(['-X', '--method'], dict(choices=METHODS, default='get', type=str.lower,
                                          help='Method used for the curl command and for completing the possible'
                                               ' urls'),
                 value_description='method'),
    ArgParserArg(['-p', '--print-cmd'], dict(action='store_true', default=False,
                                             help='Print the resulting curl command to standard out')),
    ArgParserArg(['-n', '--no-run'], dict(action='store_false', dest='run_cmd', default=True,
                                          help='Don\'t run the curl command.  Useful with -p'))
]


def add_generic_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    for arg in GENERIC_ARGS:
        parser.add_argument(*arg.name_or_flags, **arg.kwargs)
    return parser


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
