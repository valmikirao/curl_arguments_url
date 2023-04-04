"""Main module."""
import argparse
import itertools
import json
import os
import re
import shutil
import sys
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict
from datetime import datetime
from enum import Enum
from hashlib import md5
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, Callable, Any, \
    Set, MutableMapping, cast

from jsonref import replace_refs as replace_json_refs  # type: ignore
from openapi_schema_pydantic import OpenAPI, Operation, RequestBody, Schema, Reference, Parameter, PathItem
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


class Method(Enum):
    GET = 'GET'
    PUT = 'PUT'
    POST = 'POST'
    DELETE = 'DELETE'
    OPTIONS = 'OPTIONS'
    HEAD = 'HEAD'
    PATCH = 'PATCH'
    TRACE = 'TRACE'

METHODS: List[str] = list(Method.__members__.keys())


T = TypeVar('T')
V = TypeVar('V')
U = TypeVar('U')
ArgType = Callable[[str], T]


class FileCache(ABC, Generic[T, V]):
    CACHE_DIR = os.path.join(CARL_DIR, 'cache')

    def __init__(self, dir_: str):
        self._dir = os.path.join(self.CACHE_DIR, dir_)
        self._process_cache: Dict[T, V] = {}

    @abstractmethod
    def freeze(self, value: V) -> str:
        ...

    @abstractmethod
    def thaw(self, frozen_value: str) -> V:
        ...

    @abstractmethod
    def freeze_key(self, key: T) -> str:
        ...

    def clear(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)
        self._process_cache.clear()

    def _get_key_filename(self, key: T) -> str:
        key_stringified = self.freeze_key(key).encode()
        key_hash = md5(key_stringified).hexdigest()
        return os.path.join(self._dir, key_hash)

    def __getitem__(self, key: T) -> V:
        if key not in self._process_cache:
            key_filename = self._get_key_filename(key)
            if os.path.exists(key_filename):
                with open(key_filename, 'r') as fh:
                    self._process_cache[key] = self.thaw(fh.read())
            else:
                raise KeyError(key)
        return self._process_cache[key]

    def __setitem__(self, key: T, value: V) -> None:
        self._process_cache[key] = value
        os.makedirs(self._dir, exist_ok=True)
        key_filename = self._get_key_filename(key)
        frozen_value = self.freeze(value)
        with open(key_filename, 'w') as fh:
            fh.write(frozen_value)

    def get(self, key: T, default: U) -> Union[V, U]:
        try:
            return self[key]
        except KeyError:
            return default



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

BODY_ARG_SUFFIX = 'BODY'

class CarlParam(BaseModel):
    name: str
    param_type: ParamType
    description: Optional[str] = None
    required_: bool = False
    type_: ArgTypeModel = ArgTypeModel(type_=ArgTypeEnum.string)
    include_location: bool = False

    @validator('required_', pre=True)
    def required(cls, v: Any) -> bool:
        return bool(v)

    def get_arg_name(self) -> str:
        if not self.include_location:
            return f"+{self.name}"
        else:
            if self.param_type == ParamType.json_body:
                type_str = BODY_ARG_SUFFIX
            else:
                type_str = self.param_type.value.upper()
            return f"+{self.name}:{type_str}"

    @classmethod
    def param_name_from_arg_name(cls, arg_name: str) -> str:
        param_name = arg_name
        if param_name.startswith('+'):
            # strip leading '+'
            param_name = param_name[1:]
        param_type: ParamType
        for param_type in ParamType.__members__.values():
            if param_type == ParamType.json_body:
                suffix = BODY_ARG_SUFFIX
            else:
                suffix = param_type.value.upper()
            if param_name.endswith(f":{suffix}"):
                # strip the suffix
                param_name = param_name[:-len(suffix)]

        return param_name

EndpointParams = Dict[str, List[CarlParam]]


class ParamArg(Generic[T]):
    """
    Makes it so you can have `+foo a +foo b` and `+foo a b`
    """

    param: CarlParam
    values: List[T]

    def __init__(self, param: CarlParam, value_lookup: Optional[Set[str]] = None):
        self.param = param
        self.values = []

    def type_(self, val: str) -> 'ParamArg':
        self.values.append(self.param.type_.converter(val))

        return self


class SwaggerModel:
    id: str
    properties: List[CarlParam]


class EndpointToCache(BaseModel):
    endpoint_url: str
    method: Method
    parameters: List[CarlParam]
    summary: Optional[str]
    description: Optional[str]


class SwaggerEndpoint:
    params: EndpointParams
    path: str
    method: str

    @classmethod
    def from_cached_endpoint(cls, cached_endpoint: EndpointToCache) -> 'SwaggerEndpoint':
        return cls(
            url=cached_endpoint.endpoint_url,
            method=cached_endpoint.method.value,
            parameters=cached_endpoint.parameters
        )

    def __init__(self, url: str, method: str, parameters: List[CarlParam]):
        self.url = url
        self.method = method
        self.params: EndpointParams = {}
        params: EndpointParams = defaultdict(list)

        for param in parameters:
            params[param.name].append(param)

        url_params = re.findall(r'\{(.*?)\}', url, re.DOTALL)
        for param_name in url_params:
            if any(
                p.param_type == ParamType.path for p in params.get(param_name, [])
            ):
                pass
            else:
                # not sure how to warn about this yet
                # print(f"Warning: Parameter +{param_name} is in url but not explicitly declared", file=sys.stderr)
                params[param_name].append(CarlParam(
                    name=param_name,
                    param_type=ParamType.path
                ))

        for name, params_with_same_name in params.items():
            if len(params_with_same_name) > 1:
                new_params: List[CarlParam] = []
                for param in params_with_same_name:
                    new_param = param.copy()
                    new_param.include_location = True
                    new_params.append(new_param)
                self.params[name] = new_params
            else:
                self.params[name] = params_with_same_name

    def add_args_from_params(self, parser: argparse.ArgumentParser) \
            -> argparse.ArgumentParser:
        """
        Note: this is a very crude approximation of the swagger param model.
        See https://swagger.io/docs/specification/describing-parameters/ for what the possibilities really are
        """
        for params_for_name in self.params.values():
            for param in params_for_name:
                nargs: Union[int, Literal['+']] = '+' if param.type_.is_array else 1
                arg_name = param.get_arg_name()
                parser.add_argument(arg_name, type=ParamArg(param).type_, required=param.required_, nargs=nargs,
                                    help=param.description)

        return parser


DISPLAY_DESCRIPTION_IDEAL_LENGTH = 100


class UrlToCache(BaseModel):
    url: str
    summary: Optional[str]
    description: Optional[str]


class RootCacheItem(BaseModel):
    time: float
    urls: List[UrlToCache]


class RootCache(FileCache[None, RootCacheItem]):
    ROOT_CACHE_KEY = 'NO-KEY'

    def freeze(self, value: RootCacheItem) -> str:
        return value.json()

    def thaw(self, frozen_value: str) -> RootCacheItem:
        return RootCacheItem.parse_raw(frozen_value)

    def freeze_key(self, key: None) -> str:
        return self.ROOT_CACHE_KEY


class MethodsCache(FileCache[str, List[Method]]):
    def freeze(self, value: List[Method]) -> str:
        return json.dumps([
            v.value for v in value
        ])

    def thaw(self, frozen_value: str) -> List[Method]:
        return [
            Method(v) for v in json.loads(frozen_value)
        ]

    def freeze_key(self, key: str) -> str:
        return key


EndpointKey = Tuple[str, Method]


class EndpointCache(FileCache[EndpointKey, EndpointToCache]):
    def freeze(self, value: EndpointToCache) -> str:
        return value.json()

    def thaw(self, frozen_value: str) -> EndpointToCache:
        return EndpointToCache.parse_raw(frozen_value)

    def freeze_key(self, key: EndpointKey) -> str:
        url, method = key
        method_str = method.value
        return json.dumps([url, method_str])


class CompletionArgs(NamedTuple):
    word_index: int
    line: str


class GenericArgs(NamedTuple):
    print_cmd: bool = False
    run_cmd: bool = False
    util: bool = False
    completion_args: Optional[CompletionArgs] = None


class CompletionItem(NamedTuple):
    tag: str
    description: Optional[str]


UTIL_COMPLETION_ITEM = CompletionItem('util', 'Utilities')


class SwaggerRepo:

    def __init__(self, files: Optional[List[str]] = None, ephemeral: bool = False):
        if not ephemeral:
            self.root_cache = RootCache('root')
            self.methods_cache = MethodsCache('methods')
            self.endpoint_cache = EndpointCache('endpoint')
        else:
            # this is a testing case, so make all caches are ephemeral
            # casting dicts should be OK, since they should have a subset of the
            # functions implemented in FileCache
            self.root_cache = cast(RootCache, {})
            self.methods_cache = cast(MethodsCache, {})
            self.endpoint_cache = cast(EndpointCache, {})

        if files is None:
            swagger_files = [os.path.join(SWAGGER_DIR, f) for f in os.listdir(SWAGGER_DIR)]
        else:
            swagger_files = files

        root_cache_item = self.root_cache.get(None, None)
        if root_cache_item:
            cache_time = root_cache_item.time
        else:
            cache_time = 0
        yaml_files_time = max(os.path.getmtime(f) for f in swagger_files)
        if yaml_files_time > cache_time:
            self.clear_all_caches()
            self._load_swagger_data(swagger_files=swagger_files)

    def clear_all_caches(self) -> None:
        self.root_cache.clear()
        self.methods_cache.clear()
        self.endpoint_cache.clear()

    def _load_swagger_data(self, swagger_files: Optional[Iterable[str]]):
        cache_time = datetime.now().timestamp()
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

        urls_to_cache: MutableMapping[str, UrlToCache] = OrderedDict()
        methods_to_cache: MutableMapping[str, List[Method]] = defaultdict(list)
        for swagger_data_ in multi_swagger_data:
            root_description = swagger_data_.info.description
            root_summary = swagger_data_.info.summary or swagger_data_.info.title
            if swagger_data_.paths:
                server_urls = [s.url for s in swagger_data_.servers]
                for path_str, path_spec in swagger_data_.paths.items():
                    # Note: this doesn't deal with relative servers, we might need to deal with that
                    # when fetching the spec
                    if path_spec.servers:
                        server_urls_for_path = [s.url for s in swagger_data_.servers]
                    else:
                        server_urls_for_path = server_urls

                    path_description = path_spec.description or root_description
                    path_summary = path_spec.summary or root_summary

                    for method in Method.__members__.values():
                        operation = self._get_operation(path_spec, method)
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

                            op_description = operation.description or path_description
                            op_summary = operation.summary or path_summary
                            for server_url in server_urls_for_path:
                                endpoint_url = server_url + path_str
                                self.endpoint_cache[endpoint_url, method] = EndpointToCache(
                                    endpoint_url=endpoint_url,
                                    method=method,
                                    parameters=parameters,
                                    summary=op_summary,
                                    description=op_description
                                )
                                if endpoint_url not in urls_to_cache:
                                    urls_to_cache[endpoint_url] = UrlToCache(
                                        url=endpoint_url,
                                        summary=path_summary,
                                        description=path_description
                                    )
                                methods_to_cache[endpoint_url].append(method)

        for url, methods in methods_to_cache.items():
            self.methods_cache[url] = methods

        self.root_cache[None] = RootCacheItem(
            time=cache_time,
            urls=list(urls_to_cache.values())
        )

    @staticmethod
    def _get_operation(path_spec: PathItem, method: Method) -> Optional[Operation]:
        # maybe someday make this more type-safe
        return getattr(path_spec, method.value.lower())

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

    def cli_args_to_cmd(self, cli_args: Sequence[str]) \
            -> Tuple[Sequence[str], GenericArgs]:
        # url is always the first arg
        url: Optional[str] = cli_args[0] if len(cli_args) >= 1 else None

        possible_urls = self.root_cache[None].urls
        valid_url_chosen: Optional[UrlToCache]
        if url is None:
            valid_url_chosen = None
        else:
            for possible_url in possible_urls:
                if possible_url.url == url:
                    valid_url_chosen = possible_url
                    break
            else:
                valid_url_chosen = None

        if not valid_url_chosen:
            # either this is a --help request or an error
            no_url_parser = argparse.ArgumentParser(description=CARL_CMD_DESCRIPTION)
            url_subparsers = no_url_parser.add_subparsers(dest='url', required=True)

            url_subparsers = add_util_parser(url_subparsers)
            for possible_url in possible_urls:
                possible_url_desc = possible_url.description or possible_url.summary
                url_subparsers.add_parser(possible_url.url, help=possible_url_desc)

            # This should give either the correct error or correct help message
            parsed_args = no_url_parser.parse_args(cli_args)

            if parsed_args.url == 'util':
                # this is a util request, will
                return [], GenericArgs(
                    util=True,
                    completion_args=namespace_to_completion_args(parsed_args)
                )
            else:
                raise AssertionError('Should not make it here')
        else:
            url_desc = valid_url_chosen.description or valid_url_chosen.summary
            arg_parser = self.get_path_arg_parser(
                url=valid_url_chosen.url,
                url_desc=url_desc,
            )

            args = arg_parser.parse_args(cli_args)
            url_: str = args.url
            method = Method(args.method)

            remaining: List[str] = getattr(args, REMAINING_ARG) or []
            param_arg_pairs = param_args_to_pairs(args)
            cache_param_arg_pairs(param_arg_pairs)
            cached_endpoint = self.endpoint_cache[url_, method]
            selected_endpoint = SwaggerEndpoint.from_cached_endpoint(cached_endpoint)

            headers, param_arg_pairs = format_headers(param_arg_pairs)
            post_data, param_arg_pairs = format_post_data(param_arg_pairs)
            formatted_url = format_url(url_, param_arg_pairs)

            method_: str = method.value

            generic_args = GenericArgs(
                print_cmd=args.print_cmd,
                run_cmd=args.run_cmd
            )

            return ['curl', '-X', method_, formatted_url, *headers, *post_data, *remaining], generic_args

    def get_path_arg_parser(self, url: str, url_desc: Optional[str] = None) \
            -> argparse.ArgumentParser:
        url = url
        methods = self.methods_cache[url]
        arg_parser = argparse.ArgumentParser(description=CARL_CMD_DESCRIPTION)
        url_subparsers = arg_parser.add_subparsers(dest='url', required=True)
        url_parser = url_subparsers.add_parser(url, help=url_desc)
        method_subparsers = url_parser.add_subparsers(dest='method', required=True)
        for method in methods:
            endpoint = self.endpoint_cache[url, method]
            method_desc = endpoint.description or endpoint.summary
            method_parser = method_subparsers.add_parser(method.value, description=method_desc, prefix_chars='+-')
            method_parser = add_generic_args(method_parser)

            swagger_endpoint = SwaggerEndpoint.from_cached_endpoint(endpoint)
            method_parser = swagger_endpoint.add_args_from_params(method_parser)

            method_parser.add_argument(REMAINING_ARG, nargs='*', help='Extra argument passed to curl')
        return arg_parser

    def get_completions(self, index: int, words: Sequence[Optional[str]]) -> Iterable[CompletionItem]:
        words_: List[str] = []
        for word, _ in itertools.zip_longest(words, range(index + 1)):
            if word is None:
                words_.append('')
            else:
                words_.append(word)

        if index == 0:
            return 'carl'
        elif index == 1:
            # this means it's either the url or "util"
            prefix: str = words_[1] or ''
            if UTIL_COMPLETION_ITEM.tag.startswith(prefix):
                yield UTIL_COMPLETION_ITEM
            possible_urls = self.root_cache[None].urls
            for possible_url in possible_urls:
                if possible_url.url.startswith(prefix):
                    description = possible_url.summary or possible_url.description
                    yield CompletionItem(
                        tag=possible_url.url,
                        description=description
                    )
        elif index == 2:
            # this means it's a method
            url = words_[1]
            prefix = words_[2]

            possible_methods: List[Method] = self.methods_cache.get(url, [])

            for method in possible_methods:
                if method.value.startswith(prefix):
                    endpoint = self.endpoint_cache[url, method]
                    description = endpoint.summary or endpoint.description
                    yield CompletionItem(
                        tag=method.value,
                        description=description
                    )
        elif index > 2:
            url = words_[1]
            try:
                method = Method(words_[2])
            except ValueError:
                return []

            is_value_arg = self.get_arg_name_this_is_value_for(words_[3:index + 1])
            if is_value_arg is None:
                yield from self.get_param_completions(url, method, prefix=words_[index])
            else:
                values: List[ArgValue] = arg_cache.get(is_value_arg[1:], [])
                prefix = words_[index]
                for value in values:
                    if str(value).startswith(prefix):
                        yield CompletionItem(
                            tag=str(value),
                            description=None
                        )
        else:
            yield CompletionItem(
                tag=words_[index],
                description=None
            )

    def get_arg_name_this_is_value_for(self, words: List[str]) -> Optional[str]:
        # Get Rid of Generic Args
        arg_parser = argparse.ArgumentParser(add_help=False)
        arg_parser = add_generic_args(arg_parser)
        arg_parser.add_argument('--help', '-h')
        remaining_args: List[str]
        _, remaining_args = arg_parser.parse_known_args(words)

        if len(remaining_args) <= 1 or remaining_args[-1].startswith('+'):
            # not enough remaining args, or this is a param
            return None
        else:
            for arg in reversed(remaining_args[:-1]):
                if arg.startswith('+'):
                    return CarlParam.param_name_from_arg_name(arg)
            return None

    def get_param_completions(self, url: str, method: Method, prefix: str):
        if prefix == '' or prefix.startswith('-'):
            for generic_arg in GENERIC_OPTIONAL_ARGS:
                for tag in generic_arg.name_or_flags:
                    if tag.startswith(prefix):
                        yield CompletionItem(
                            tag=tag,
                            description=generic_arg.kwargs['help']
                        )
        if prefix == '' or prefix.startswith('+'):
            cached_endpoint = self.endpoint_cache[url, Method(method)]
            endpoint = SwaggerEndpoint.from_cached_endpoint(cached_endpoint)
            for params_for_name in endpoint.params.values():
                for param in params_for_name:
                    tag = param.get_arg_name()
                    if tag.startswith(prefix):
                        yield CompletionItem(
                            tag=tag,
                            description=param.description
                        )


CARL_CMD_DESCRIPTION = "TBD"


def add_util_parser(parser: Any) -> Any:
    util_parser: argparse.ArgumentParser = parser.add_parser(
        UTIL_COMPLETION_ITEM.tag, description=UTIL_COMPLETION_ITEM.description
    )
    util_type_subparsers = util_parser.add_subparsers(dest='util_type', required=True)

    zsh_completion_parser = util_type_subparsers.add_parser('zsh-completion', description='Return completions')
    zsh_completion_parser.add_argument('word_index', type=int)
    zsh_completion_parser.add_argument('line')

    return parser


def namespace_to_completion_args(namespace: argparse.Namespace) -> Optional[CompletionArgs]:
    if namespace.util_type == 'zsh-completion':
        return CompletionArgs(
            word_index=namespace.word_index,
            line=namespace.line
        )
    else:
        return None


ArgValue = Union[str, int, float, Dict[str, 'ArgValue'], List['ArgValue']]


ArgPairs = List[Tuple[CarlParam, ArgValue]]

MAX_HISTORY = 200


class ArgCache(FileCache[str, List[ArgValue]]):
    def freeze(self, value: List[ArgValue]) -> str:
        return json.dumps(value)

    def thaw(self, frozen_value: str) -> List[ArgValue]:
        return cast(List[ArgValue], json.loads(frozen_value))

    def freeze_key(self, key: str) -> str:
        return key


arg_cache = ArgCache('args')


def cache_param_arg_pairs(param_args: ArgPairs) -> None:
    for param, value in param_args:
        key = param.name
        arg_history: List[ArgValue] = arg_cache.get(key, [])

        new_history: List[ArgValue] = [value] + [a for a in arg_history if a != value]
        new_history = new_history[:MAX_HISTORY]
        arg_cache[key] = new_history


def format_post_data(param_args: ArgPairs) -> Tuple[List[str], ArgPairs]:
    remaining_argpairs: ArgPairs = []
    post_data: Dict[str, Any] = {}

    for param, arg_value in param_args:
        if param.param_type == ParamType.json_body:
            arg_name = param.name
            if param.type_.is_array:
                if arg_name not in post_data:
                    post_data[arg_name] = [arg_value]
                else:
                    post_data[arg_name].append(arg_value)
            else:
                post_data[arg_name] = arg_value
        else:
            remaining_argpairs.append((param, arg_value),)

    if post_data:
        formatted_postdata = ['-H', 'Content-Type: application/json', '--data-binary', json.dumps(post_data)]
    else:
        formatted_postdata = []

    return formatted_postdata, remaining_argpairs


def format_headers(param_args: ArgPairs) -> Tuple[List[str], ArgPairs]:
    remaining_argpairs: ArgPairs = []
    headers: List[str] = []
    for param, arg_value in param_args:
        if param.param_type == ParamType.header:
            headers.extend(['-H', f"{param.name}: {arg_value}"])
        else:
            remaining_argpairs.append((param, arg_value),)

    return headers, remaining_argpairs


def format_url(url_template: str, param_args: ArgPairs) -> str:
    query_args: List[Tuple[str, str]] = []
    returned_url = url_template

    for param, arg_value in param_args:
        arg_name = param.name
        if isinstance(arg_value, str):
            arg_value_str = arg_value
        else:
            # This shouldn't be anything complicate, but just in case
            arg_value_str = json.dumps(arg_value)

        if param.param_type == ParamType.path:
            returned_url = re.sub(r'\{%s\}' % arg_name, arg_value_str, returned_url)
        elif param.param_type == ParamType.query:
            query_args.append((arg_name, arg_value_str),)
        else:
            # We shouldn't get here, but I'm not confident endough of this to
            # put a "raise NotImplementedError()" here
            pass
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
            key = param_value.param
            for val in param_value.values:
                args_pairs.append((key, val),)

    return args_pairs


class ArgParserArg(NamedTuple):
    name_or_flags: List[str]
    kwargs: Dict[str, Any]
    value_description: Optional[str] = None

    def add_to_parser(self, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument(*self.name_or_flags, **self.kwargs)
        return parser


def get_url_arg(*, required: bool, urls: Optional[List[str]] = None) -> ArgParserArg:
    kwargs: Dict[str, Any] = {'help': 'Url of endpoint'}
    if not required:
        kwargs['nargs'] = '?'
    if urls is not None:
        kwargs['choices'] = urls
    return ArgParserArg(['url'], kwargs=kwargs)


GENERIC_OPTIONAL_ARGS = [
    ArgParserArg(['-p', '--print-cmd'], dict(action='store_true', default=False,
                                             help='Print the resulting curl command to standard out')),
    ArgParserArg(['-n', '--no-run'], dict(action='store_false', dest='run_cmd', default=True,
                                          help='Don\'t run the curl command.  Useful with -p'))
]


def add_generic_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    for arg in GENERIC_OPTIONAL_ARGS:
        parser = arg.add_to_parser(parser)
    return parser
