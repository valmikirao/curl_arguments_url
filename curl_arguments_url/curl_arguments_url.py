"""Main module."""
import argparse
import itertools
import json
import os
import re
import shutil
import sys
import textwrap
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict
from copy import deepcopy
from datetime import datetime
from enum import Enum
from hashlib import md5
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, \
    Callable, Any, MutableMapping, cast, Set

from jsonref import replace_refs as replace_json_refs  # type: ignore
from openapi_schema_pydantic import OpenAPI, Operation, RequestBody, Schema, Reference, Parameter, PathItem, Server
from pydantic import BaseModel, validator
from typing_extensions import Literal
from urllib.parse import urlencode
import yaml
import yaml.parser

REMAINING_ARG = 'passed_to_curl'

ParamValue = Union[str, int, float, Dict[str, Any], List[Any]]


class EnvVariable:
    registry: List['EnvVariable'] = []

    def __init__(self, env_name: str, default: str, description: str):
        self.env_name = env_name
        self.default = default
        self.description = description

        self.registry.append(self)

    def get_value(self) -> str:
        return os.environ.get(self.env_name, self.default)


CARL_DIR_ENV = EnvVariable(
    'CARL_DIR', os.path.join(os.environ.get('HOME', '/'), '.carl'),
    description='Directory which contains files for carl. Default: ~/.carl'
)
CARL_DIR = CARL_DIR_ENV.get_value()
OPEN_API_DIR_ENV = EnvVariable(
    'CARL_OPEN_API_DIR', os.path.join(CARL_DIR, 'open_api'),
    description='Directory containing the OpenApi specifications and Yaml files. Default: $CARL_DIR/open_api'
)
OPEN_API_DIR = OPEN_API_DIR_ENV.get_value()
CACHE_DIR_ENV = EnvVariable(
    'CARL_CACHE_DIR', os.path.join(CARL_DIR, 'cache'),
    description='Directory containing the cache. Default $CARL_DIR/cache'
)
CACHE_DIR = CACHE_DIR_ENV.get_value()


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
    def __init__(self, dir_: str):
        self._dir = os.path.join(CACHE_DIR, dir_)
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

    def default(self) -> ParamValue:
        return ARG_TYPE_DEFAULTS[self.type_]


ARG_TYPE_FUNCS: Dict[ArgTypeEnum, ArgType] = {
    ArgTypeEnum.string: str,
    ArgTypeEnum.integer: int,
    ArgTypeEnum.number: float,
    ArgTypeEnum.boolean: boolean_type,
    ArgTypeEnum.json: json.loads
}

ARG_TYPE_DEFAULTS: Dict[ArgTypeEnum, ParamValue] = {
    ArgTypeEnum.string: '',
    ArgTypeEnum.integer: 0,
    ArgTypeEnum.number: 0.0,
    ArgTypeEnum.boolean: False,
    ArgTypeEnum.json: {}
}


class ParamType(Enum):
    query = 'query'
    path = 'path'
    header = 'header'
    json_body = 'json_body'


class CarlParamReference(NamedTuple):
    param_name: str
    param_type: Optional[ParamType]


BODY_ARG_SUFFIX = 'BODY'


class CarlParam(BaseModel):
    name: str
    param_type: ParamType
    description: Optional[str] = None
    required_: bool = False
    type_: ArgTypeModel = ArgTypeModel(type_=ArgTypeEnum.string)
    include_location: bool = False
    enums: Optional[List[ParamValue]] = None
    default: Optional[ParamValue] = None

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
    def param_ref_from_arg_name(cls, arg_name: str) -> CarlParamReference:
        param_name = arg_name
        if param_name.startswith('+'):
            # strip leading '+'
            param_name = param_name[1:]
        param_type: Optional[ParamType] = None
        possible_param_type: ParamType
        for possible_param_type in ParamType.__members__.values():
            if possible_param_type == ParamType.json_body:
                suffix = BODY_ARG_SUFFIX
            else:
                suffix = possible_param_type.value.upper()
            if param_name.endswith(f":{suffix}"):
                # strip the suffix
                param_name = param_name[:-len(suffix)]
                param_type = possible_param_type

        return CarlParamReference(
            param_name=param_name,
            param_type=param_type
        )


EndpointParams = Dict[str, List[CarlParam]]

MAX_HISTORY = 200

ArgPairs = List[Tuple[CarlParam, ParamValue]]


class ParamArg():
    """
    Makes it so you can have `+foo a +foo b` and `+foo a b`
    """

    param: CarlParam
    values: List[ParamValue]

    def __init__(self, param: CarlParam, values: Optional[Iterable[ParamValue]] = None):
        self.param = param
        if values:
            self.values = list(values)
        else:
            self.values = []

    def type_(self, val: str) -> 'ParamArg':
        self.values.append(self.param.type_.converter(val))

        return self

    def __eq__(self, other) -> bool:
        if isinstance(other, type(self)):
            return self.param is other.param and self.values == other.values
        else:
            return False

    def __repr__(self):
        if len(self.values) == 1:
            return param_value_to_str(self.values[0])
        else:
            return repr([param_value_to_str(v) for v in self.values])

    def __hash__(self) -> int:
        return hash(json.dumps({
            'param': self.param.json(),
            'values': [param_value_to_str(v) for v in self.values]
        }))


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
                # not sure how to warn about this yet, or if I should warn about it
                # print(f"Warning: Parameter +{param_name} is in url but not explicitly declared", file=sys.stderr)
                params[param_name].append(CarlParam(
                    name=param_name,
                    param_type=ParamType.path,
                    required_=True
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

    def add_args_from_params(self, parser: argparse.ArgumentParser, use_requires: bool) \
            -> argparse.ArgumentParser:
        """
        Note: this is a very crude approximation of the swagger param model.
        See https://swagger.io/docs/specification/describing-parameters/ for what the possibilities really are
        """
        for params_for_name in self.params.values():
            for param in params_for_name:
                nargs: Union[int, Literal['+']] = '+' if param.type_.is_array else 1
                arg_name = param.get_arg_name()
                choices: Optional[str]
                if use_requires and param.enums:
                    enums = [ParamArg(param, [e]) for e in param.enums]
                else:
                    enums = None
                required = use_requires and param.required_
                parser.add_argument(
                    arg_name,
                    type=ParamArg(param).type_,
                    required=required,
                    choices=enums,
                    nargs=nargs,
                    help=param.description
                )

        return parser


DISPLAY_DESCRIPTION_IDEAL_LENGTH = 100


class UrlToCache(BaseModel):
    url: str
    summary: Optional[str]
    description: Optional[str]


class RootCacheItem(BaseModel):
    time: float
    urls: List[UrlToCache]
    params_with_cached_values: List[str] = []


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


class ValuesRmArgs(NamedTuple):
    param_name: str
    value: str


class ValuesAddArgs(NamedTuple):
    param_name: str
    values: List[str]


class GenericArgs(NamedTuple):
    print_cmd: bool = False
    run_cmd: bool = False
    util: bool = False
    zsh_completion_args: Optional[CompletionArgs] = None
    zsh_print_script: bool = False
    values_list_params: bool = False
    values_ls_for_param: Optional[str] = None
    values_rm_args: Optional[ValuesRmArgs] = None
    values_add_args: Optional[ValuesAddArgs] = None
    rebuild_cache: bool = False


class CompletionItem(NamedTuple):
    tag: str
    description: Optional[str]


UTILS_COMPLETION_ITEM = CompletionItem('utils', 'Utilities')


class CarlServer(NamedTuple):
    url: str
    params: List[CarlParam]


class SwaggerRepo:

    def __init__(self, files: Optional[List[str]] = None, ephemeral: bool = False, warnings: bool = True):
        if not ephemeral:
            self.root_cache = RootCache('root')
            self.methods_cache = MethodsCache('methods')
            self.endpoint_cache = EndpointCache('endpoint')
            self.arg_value_cache = ArgCache('arg_values')
        else:
            # this is a testing case, so make all caches are ephemeral
            # casting dicts should be OK, since they should have a subset of the
            # functions implemented in FileCache
            self.root_cache = cast(RootCache, {})
            self.methods_cache = cast(MethodsCache, {})
            self.endpoint_cache = cast(EndpointCache, {})
            self.arg_value_cache = cast(ArgCache, {})

        if files is None:
            os.makedirs(OPEN_API_DIR, exist_ok=True)
            swagger_files = list(get_files_in_dir(OPEN_API_DIR))
        else:
            swagger_files = files

        root_cache_item = self.root_cache.get(None, None)

        if len(swagger_files) == 0 and root_cache_item:
            # make sure the cached data is clear
            if len(root_cache_item.urls) > 0:
                self.clear_all_spec_caches()
        elif len(swagger_files) == 0:
            # nothing to clear
            pass
        else:
            if root_cache_item:
                cache_time = root_cache_item.time
            else:
                cache_time = 0
            yaml_files_time = max(os.path.getmtime(f) for f in swagger_files)
            if yaml_files_time > cache_time:
                self.clear_all_spec_caches()
                self.load_swagger_data(swagger_files=swagger_files, warnings=warnings)

    def clear_all_spec_caches(self) -> None:
        self.root_cache.clear()
        self.methods_cache.clear()
        self.endpoint_cache.clear()

    def load_swagger_data(self, swagger_files: Optional[Iterable[str]], warnings: bool = False):
        cache_time = datetime.now().timestamp()
        multi_swagger_data: List[OpenAPI] = []
        if swagger_files is not None:
            for file in swagger_files:
                with open(file, 'r') as fh:
                    loaded: Optional[Dict[str, Any]]
                    try:
                        loaded = yaml.safe_load(fh)
                    except yaml.parser.ParserError as e:
                        if warnings:
                            print('WARNING: ' + str(e), file=sys.stderr)
                        loaded = None
                    if loaded is not None:
                        try:
                            loaded = replace_json_refs(loaded, merge_props=True)
                            multi_swagger_data.append(OpenAPI.parse_obj(loaded))
                        except Exception as e:
                            if warnings:
                                print(f"WARNING: Error in file {file!r}: {str(e)}", file=sys.stderr)
                            else:
                                # fail silently
                                pass
                    elif warnings:
                        print(f"WARNING: Yaml error in file {file!r}", file=sys.stderr)
                    else:
                        # fail silently
                        pass

        urls_to_cache: MutableMapping[str, UrlToCache] = OrderedDict()
        methods_to_cache: MutableMapping[str, List[Method]] = defaultdict(list)
        for swagger_data_ in multi_swagger_data:
            root_description = swagger_data_.info.description
            root_summary = swagger_data_.info.summary or swagger_data_.info.title

            carl_servers = list(self.to_carl_servers(swagger_data_.servers))
            if swagger_data_.paths:
                for path_str, path_spec in swagger_data_.paths.items():
                    # Note: this doesn't deal with relative servers, we might need to deal with that
                    # when fetching the spec
                    carl_servers_for_path: List[CarlServer]
                    if path_spec.servers:
                        servers_for_path = list(self.to_carl_servers(path_spec.servers))
                    else:
                        servers_for_path = carl_servers

                    path_description = path_spec.description or root_description
                    path_summary = path_spec.summary or root_summary

                    for method in Method.__members__.values():
                        operation = self._get_operation(path_spec, method)
                        if operation:
                            if operation.servers:
                                servers_for_op = list(self.to_carl_servers(operation.servers))
                            else:
                                servers_for_op = servers_for_path
                            op_params: List[CarlParam] = []
                            for parameter in operation.parameters or []:
                                if isinstance(parameter, Parameter):
                                    param_type = self.schema_to_arg_type(parameter.param_schema)
                                    enums: Optional[ParamValue]
                                    if isinstance(parameter.param_schema, Schema):
                                        enums = parameter.param_schema.enum
                                    else:
                                        enums = None
                                    op_params.append(CarlParam(
                                        name=parameter.name,
                                        param_type=ParamType(parameter.param_in),
                                        description=parameter.description,
                                        required_=parameter.required,
                                        type_=param_type,
                                        enums=enums
                                    ))
                                else:  # is a Reference
                                    # Hopefully we have already resolved the references
                                    pass
                            if isinstance(operation.requestBody, RequestBody):
                                params_from_body = self._get_params_from_body(operation.requestBody)
                                op_params.extend(params_from_body)

                            op_description = operation.description or path_description
                            op_summary = operation.summary or path_summary
                            for server in servers_for_op:
                                endpoint_url = server.url + path_str
                                parameters = server.params + op_params
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
    def to_carl_servers(servers: List[Server]) -> Iterable[CarlServer]:
        for server in servers:
            server_params: List[CarlParam] = []
            defaulted_url: Optional[str] = None
            if server.variables is not None:
                defaults: Dict[str, str] = {}
                for variable_name, variable_spec in server.variables.items():
                    # this casting shouldn't be necessary, but mypy isn't happy it without it
                    variable_enums = cast(Optional[List[ParamValue]], variable_spec.enum)
                    server_params.append(CarlParam(
                        name=variable_name,
                        param_type=ParamType.path,
                        description=variable_spec.description,
                        enums=variable_enums,
                        required_=False,
                        default=variable_spec.default
                    ))
                    defaults[variable_name] = variable_spec.default
                try:
                    defaulted_url = server.url.format(**defaults)
                except KeyError:
                    pass
            if defaulted_url is not None:
                yield CarlServer(defaulted_url, [])
            yield CarlServer(server.url, server_params)

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
                            enums = prop_schema.enum
                        else:
                            description = None
                            enums = None

                        yield CarlParam(
                            name=prop_name,
                            param_type=ParamType.json_body,
                            description=description,
                            required_=(prop_name in required_props),
                            type_=carl_param_type,
                            enums=enums
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

        root_cache_item = self.root_cache.get(None, None)
        possible_urls: List[UrlToCache]
        if root_cache_item:
            possible_urls = root_cache_item.urls
        else:
            possible_urls = []
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
            no_url_parser = get_arg_parser()
            url_subparsers = no_url_parser.add_subparsers(dest='url', required=True)

            url_subparsers = add_utils_parser(url_subparsers)
            for possible_url in possible_urls:
                possible_url_desc = possible_url.description or possible_url.summary
                url_subparsers.add_parser(possible_url.url, help=possible_url_desc)

            # This should give either the correct error or correct help message
            parsed_args = no_url_parser.parse_args(cli_args)

            if parsed_args.url == UTILS_COMPLETION_ITEM.tag:
                # this is a util request, will
                values_ls_for_param: Optional[str]
                if parsed_args.util_type == VALUES_COMPLETION.tag \
                        and parsed_args.cached_values_type == VALUES_LS_COMPLETION.tag:
                    values_ls_for_param = parsed_args.param_name
                else:
                    values_ls_for_param = None
                values_rm_args: Optional[ValuesRmArgs]
                if parsed_args.util_type == VALUES_COMPLETION.tag \
                        and parsed_args.cached_values_type == VALUES_RM_COMPLETION.tag:
                    values_rm_args = ValuesRmArgs(
                        param_name=parsed_args.param_name,
                        value=parsed_args.value
                    )
                else:
                    values_rm_args = None
                values_add_args: Optional[ValuesAddArgs]
                if parsed_args.util_type == VALUES_COMPLETION.tag and \
                        parsed_args.cached_values_type == VALUES_ADD_COMPLETION.tag:
                    values_add_args = ValuesAddArgs(
                        param_name=parsed_args.param_name,
                        values=parsed_args.value
                    )
                else:
                    values_add_args = None
                return [], GenericArgs(
                    util=True,
                    zsh_completion_args=namespace_to_zsh_completion_args(parsed_args),
                    zsh_print_script=(parsed_args.util_type == ZSH_PRINT_SCRIPT_COMPLETION.tag),
                    values_list_params=(
                        parsed_args.util_type == VALUES_COMPLETION.tag
                        and parsed_args.cached_values_type == VALUES_PARAMS_COMPLETION.tag
                    ),
                    values_ls_for_param=values_ls_for_param,
                    values_rm_args=values_rm_args,
                    values_add_args=values_add_args,
                    rebuild_cache=(parsed_args.util_type == REBUILD_CACHE_COMPLETION.tag)
                )
            else:
                raise AssertionError('Should not make it here')
        else:
            url_desc = valid_url_chosen.description or valid_url_chosen.summary
            use_requires = get_use_requires(cli_args)
            arg_parser = self.get_path_arg_parser(
                url=valid_url_chosen.url,
                url_desc=url_desc,
                use_requires=use_requires
            )

            args = arg_parser.parse_args(cli_args)
            url_: str = args.url
            method = Method(args.method)

            remaining: List[str] = getattr(args, REMAINING_ARG) or []
            param_arg_pairs = param_args_to_pairs(args)
            self.cache_param_arg_pairs(param_arg_pairs)

            headers, param_arg_pairs = format_headers(param_arg_pairs)
            initial_post_data: Dict[str, Any] = args.body_json
            post_data, param_arg_pairs = format_post_data(param_arg_pairs, initial_post_data)
            formatted_url = format_url(url_, param_arg_pairs)

            method_: str = method.value

            generic_args = GenericArgs(
                print_cmd=args.print_cmd,
                run_cmd=args.run_cmd
            )

            return ['curl', '-X', method_, formatted_url, *headers, *post_data, *remaining], generic_args

    def cache_param_arg_pairs(self, param_args: ArgPairs) -> None:
        param_names: List[str] = []
        for param, value in param_args:
            key = param.name
            param_names.append(key)
            arg_history: List[ParamValue] = self.arg_value_cache.get(key, [])

            new_history: List[ParamValue] = [value] + [a for a in arg_history if a != value]
            new_history = new_history[:MAX_HISTORY]
            self.arg_value_cache[key] = new_history
        root_cache_item = self.root_cache[None]
        existing_param_names = root_cache_item.params_with_cached_values
        params_with_cached_values = list(set(param_names + existing_param_names))
        params_with_cached_values = sorted(params_with_cached_values)
        root_cache_item.params_with_cached_values = params_with_cached_values
        self.root_cache[None] = root_cache_item

    def get_path_arg_parser(self, url: str, use_requires: bool, url_desc: Optional[str] = None) \
            -> argparse.ArgumentParser:
        url = url
        methods = self.methods_cache[url]
        arg_parser = get_arg_parser()
        url_subparsers = arg_parser.add_subparsers(dest='url', required=True)
        url_parser = url_subparsers.add_parser(url, help=url_desc)
        method_subparsers = url_parser.add_subparsers(dest='method', required=True)
        for method in methods:
            endpoint = self.endpoint_cache[url, method]
            method_desc = endpoint.description or endpoint.summary
            method_parser = method_subparsers.add_parser(method.value, description=method_desc, prefix_chars='+-')
            method_parser = add_generic_args(method_parser)

            swagger_endpoint = SwaggerEndpoint.from_cached_endpoint(endpoint)
            method_parser = swagger_endpoint.add_args_from_params(method_parser, use_requires=use_requires)

            method_parser.add_argument(REMAINING_ARG, nargs='*',
                                       help='Extra argument passed to curl, often after "--"')
        return arg_parser

    def get_completions(self, index: int, words: Sequence[Optional[str]]) -> Iterable[CompletionItem]:
        words_: List[str] = []
        for word, _ in itertools.zip_longest(words, range(index + 1)):
            if word is None:
                words_.append('')
            else:
                words_.append(word)
        items_to_return: List[CompletionItem] = []
        if index == 0:
            items_to_return.append(CompletionItem(tag='carl', description=None))
        elif index == 1:
            # this means it's either the url or "utils"
            prefix: str = words_[1] or ''
            if UTILS_COMPLETION_ITEM.tag.lower().startswith(prefix.lower()):
                items_to_return.append(UTILS_COMPLETION_ITEM)
            root_cache = self.root_cache.get(None, None)
            if root_cache:
                possible_urls = root_cache.urls
            else:
                possible_urls = []
            for possible_url in possible_urls:
                if possible_url.url.lower().startswith(prefix.lower()):
                    description = possible_url.summary or possible_url.description
                    items_to_return.append(CompletionItem(
                        tag=possible_url.url,
                        description=description
                    ))
        elif index >= 2 and words_[1] == UTILS_COMPLETION_ITEM.tag:
            items_to_return = list(self.get_util_completions(index - 2, words_[2:]))
        elif index == 2:
            # this means it's a method
            url = words_[1]
            prefix = words_[2]

            possible_methods: List[Method] = self.methods_cache.get(url, [])

            for method in possible_methods:
                if method.value.lower().startswith(prefix.lower()):
                    endpoint = self.endpoint_cache[url, method]
                    description = endpoint.summary or endpoint.description
                    items_to_return.append(CompletionItem(
                        tag=method.value,
                        description=description
                    ))
        elif index > 2:
            url = words_[1]
            try:
                method = Method(words_[2])
            except ValueError:
                return []

            param_ref = self.get_param_ref_this_is_value_for(words_[3:index + 1])
            prefix = words_[index]
            if param_ref is None:
                items_to_return.extend(self.get_param_completions(url, method, prefix=prefix))
            else:
                enums = self.get_enums(url, method, param_ref)
                if enums is not None:
                    items_to_return.extend(get_completions_from_param_values(
                        enums, prefix=prefix
                    ))
                else:
                    items_to_return.extend(self.get_completions_for_values_for_param(param_ref.param_name, prefix))
        else:
            items_to_return.append(CompletionItem(
                tag=words_[index],
                description=None
            ))

        return sorted(items_to_return, key=lambda x: x.tag)

    def get_enums(self, url: str, method: Method, param_ref: CarlParamReference) -> Optional[List[ParamValue]]:
        cached_endpoint = self.endpoint_cache[url, Method(method)]
        endpoint = SwaggerEndpoint.from_cached_endpoint(cached_endpoint)
        param: Optional[CarlParam]
        if param_ref.param_name in endpoint.params:
            params_for_name = endpoint.params[param_ref.param_name]
            if param_ref.param_type is not None:
                for param_for_name in params_for_name:
                    if param_for_name.param_type == param_ref.param_type:
                        param = param_for_name
                        break
                else:
                    param = None
            elif len(params_for_name) == 1:
                param = params_for_name[0]
            else:
                param = None
        else:
            param = None

        if param:
            return param.enums
        else:
            return None

    def get_completions_for_values_for_param(self, param_name: str, prefix,
                                             always_return_something: bool = True) \
            -> List[CompletionItem]:
        values = self.get_ls_values_for_param(param_name)
        items_to_return: List[CompletionItem] = []
        for value in values:
            if value.lower().startswith(prefix.lower()):
                items_to_return.append(CompletionItem(
                    tag=str(value),
                    description=None
                ))
        if always_return_something and len(items_to_return) == 0:
            # if nothing in the cache matches, return the item itself so it doesn't get blanked out
            items_to_return = [CompletionItem(tag=prefix, description=None)]
        return items_to_return

    def get_param_ref_this_is_value_for(self, words: List[str]) -> Optional[CarlParamReference]:
        # Get Rid of Generic Args, except from the last word
        arg_parser = argparse.ArgumentParser(add_help=False)
        arg_parser = add_generic_args(arg_parser)
        arg_parser.add_argument('--help', '-h')
        remaining_args: List[str]
        _, remaining_args = arg_parser.parse_known_args(words[:-1])
        remaining_args.append(words[-1])

        if len(remaining_args) <= 1 or remaining_args[-1].startswith('+'):
            # not enough remaining args, or this is a param
            return None
        elif len(remaining_args) >= 3 and remaining_args[-1].startswith('-') \
                and remaining_args[-3].startswith('+'):
            # special case: ... "+foo value -" should autocomplete to generic args
            return None
        else:
            for arg in reversed(remaining_args[:-1]):
                if arg.startswith('+'):
                    return CarlParam.param_ref_from_arg_name(arg)
            return None

    def get_param_completions(self, url: str, method: Method, prefix: str):
        if prefix == '' or prefix.startswith('-'):
            for generic_arg in GENERIC_OPTIONAL_ARGS:
                for tag in generic_arg.name_or_flags:
                    if tag.lower().startswith(prefix.lower()):
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
                    if tag.lower().startswith(prefix.lower()):
                        yield CompletionItem(
                            tag=tag,
                            description=param.description
                        )

    def get_params_with_cached_values(self) -> Iterable[str]:
        root_cache_item = self.root_cache[None]
        return root_cache_item.params_with_cached_values

    def get_util_completions(self, index: int, words: List[str]) -> Iterable[CompletionItem]:
        def _from_list(prefix: str, completions_list: List[CompletionItem]) -> Iterable[CompletionItem]:
            for completion in completions_list:
                if completion.tag.startswith(prefix):
                    yield completion

        if index == 0:
            yield from _from_list(words[0], UTIL_TYPE_COMPLETIONS)
        elif index == 1 and words[0] == VALUES_COMPLETION.tag:
            yield from _from_list(words[1], VALUE_TYPES_COMPLETION)
        elif index == 2 and words[1] in (
                VALUES_LS_COMPLETION.tag, VALUES_RM_COMPLETION.tag, VALUES_ADD_COMPLETION.tag
        ):
            root_item = self.root_cache[None]
            for param_name in root_item.params_with_cached_values:
                if param_name.startswith(words[2]):
                    yield CompletionItem(
                        tag=param_name,
                        description=None
                    )
        elif index == 3 and words[1] == VALUES_RM_COMPLETION.tag:
            yield from self.get_completions_for_values_for_param(
                param_name=words[2],
                prefix=words[3],
                always_return_something=False
            )
        else:
            return []

    def get_ls_values_for_param(self, param_name: str) -> Iterable[str]:
        values: List[ParamValue] = self.arg_value_cache.get(param_name, [])
        for value in values:
            yield param_value_to_str(value)

    def remove_cached_value_for_param(self, param_name: str, value: str) -> None:
        existing_values = self.arg_value_cache[param_name]
        new_values: List[ParamValue] = []
        for existing_value in existing_values:
            existing_value_str = param_value_to_str(existing_value)
            if existing_value_str != value:
                new_values.append(existing_value_str)
        self.arg_value_cache[param_name] = new_values

        if len(new_values) == 0:
            # remove from the list of params with cached values
            root_cache_item = self.root_cache[None]
            root_cache_item.params_with_cached_values = [
                p for p in root_cache_item.params_with_cached_values if p != param_name
            ]
            self.root_cache[None] = root_cache_item

    def add_values(self, param_name: str, values: List[str]) -> None:
        # it's easiest to use cache_param_arg_pairs() to be consistent
        # with how we cache these, though we might want to refactor this to be less awkward
        # at some point
        arg_pairs: ArgPairs = []
        param = CarlParam(
            name=param_name,
            param_type=ParamType.query  # param_type doesn't matter here
        )
        for value in values:
            arg_pairs.append((param, value),)

        self.cache_param_arg_pairs(arg_pairs)


def param_value_to_str(value: ParamValue) -> str:
    if any(isinstance(value, t) for t in (str, int, float)):
        return str(value)
    else:
        return json.dumps(value)


def get_width():
    """ This is what HelpFormatted does for default width """
    try:
        width = int(os.environ['COLUMNS'])
    except (KeyError, ValueError):
        width = 80
    width -= 2

    return width


def get_completions_from_param_values(param_values: Iterable[ParamValue], prefix: str = '') -> Iterable[CompletionItem]:
    for param_value in param_values:
        param_value_str = param_value_to_str(param_value)
        if param_value_str.lower().startswith(prefix.lower()):
            yield CompletionItem(
                tag=param_value_str,
                description=None
            )


def get_files_in_dir(dir_name: str) -> Iterable[str]:
    for sub_dir_name, _, file_names in os.walk(dir_name):
        for file_name in file_names:
            yield os.path.join(sub_dir_name, file_name)


def get_command_description() -> str:
    unformatted_text = \
        f"A Utility to cleanly take command-line arguments, for an endpoint you have the OpenAPI specification for," \
        f" and convert them into an appropriate curl command.  Spec files should be in {OPEN_API_DIR_ENV.default}" \
        f" directory or directory defined by env variables (See below)"
    return wrap_text(unformatted_text)


def wrap_text(unformatted_text, **kwargs):
    width = get_width()
    return_str = ''
    for line in textwrap.wrap(unformatted_text, width, **kwargs):
        return_str += line + "\n"
    return return_str


def get_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=get_command_description(),
        epilog=get_command_epilogue(),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )


def get_command_epilogue() -> str:
    return_str = 'Environment Variables:\n'
    for env_variable in EnvVariable.registry:
        return_str += wrap_text(
            f"{env_variable.env_name}: {env_variable.description}\n",
            initial_indent=' ' * 4,
            subsequent_indent=' ' * 24
        )
    return return_str


ZSH_COMPLETION_ITEM = CompletionItem('zsh-completion', 'Return completions for zsh')
ZSH_PRINT_SCRIPT_COMPLETION = CompletionItem('zsh-print-script', 'Print the zsh script that enables completions')
REBUILD_CACHE_COMPLETION = CompletionItem('rebuild-spec-cache', 'Clear and rebuild the cache of the OpenAPI spec data')
VALUES_COMPLETION = CompletionItem('cached-values', 'Utilities to help with cached values for completions')
VALUES_PARAMS_COMPLETION = CompletionItem('params', 'List all the param names that have values cached')
VALUES_LS_COMPLETION = CompletionItem('ls', 'List all the values cached for a particular param')
VALUES_RM_COMPLETION = CompletionItem('rm', 'Remove a value for an param from the cache for completions')
VALUES_ADD_COMPLETION = CompletionItem('add', 'Add one or more values for a param to the cache')
UTIL_TYPE_COMPLETIONS = [
    ZSH_COMPLETION_ITEM,
    ZSH_PRINT_SCRIPT_COMPLETION,
    REBUILD_CACHE_COMPLETION,
    VALUES_COMPLETION
]

VALUE_TYPES_COMPLETION = [
    VALUES_PARAMS_COMPLETION,
    VALUES_LS_COMPLETION,
    VALUES_RM_COMPLETION,
    VALUES_ADD_COMPLETION
]

VALUES_SUBPARSER_DEST = 'cached_values_type'


def add_utils_parser(parser: Any) -> Any:
    # type annotations "Any" because argparse.subparser doesn't have
    # nice typs
    util_parser: argparse.ArgumentParser = parser.add_parser(
        UTILS_COMPLETION_ITEM.tag, help=UTILS_COMPLETION_ITEM.description
    )
    util_type_subparsers = util_parser.add_subparsers(dest='util_type', required=True)

    zsh_completion_parser = util_type_subparsers.add_parser(
        ZSH_COMPLETION_ITEM.tag, help=ZSH_COMPLETION_ITEM.description
    )
    zsh_completion_parser.add_argument('word_index', type=int)
    zsh_completion_parser.add_argument('line')

    util_type_subparsers.add_parser(ZSH_PRINT_SCRIPT_COMPLETION.tag,
                                    help=ZSH_PRINT_SCRIPT_COMPLETION.description)

    values_parser = util_type_subparsers.add_parser(
        VALUES_COMPLETION.tag, help=VALUES_COMPLETION.description
    )

    values_subparsers = values_parser.add_subparsers(dest=VALUES_SUBPARSER_DEST)
    values_subparsers.add_parser(VALUES_PARAMS_COMPLETION.tag, help=VALUES_PARAMS_COMPLETION.description)

    values_ls_parser = values_subparsers.add_parser(VALUES_LS_COMPLETION.tag,
                                                    help=VALUES_LS_COMPLETION.description)
    values_ls_parser.add_argument('param_name', help='Name of parameter to get cached values for')

    values_rm_parser = values_subparsers.add_parser(VALUES_RM_COMPLETION.tag,
                                                    help=VALUES_RM_COMPLETION.description)
    values_rm_parser.add_argument('param_name', help='Name of parameter to get cached values for')
    values_rm_parser.add_argument('value', help='Cached value to remove')

    values_add_parser = values_subparsers.add_parser(VALUES_ADD_COMPLETION.tag, help=VALUES_ADD_COMPLETION.description)
    values_add_parser.add_argument('param_name', help='Name of parameter to cache value for')
    values_add_parser.add_argument('value', nargs='+', help='One or more values to cache')

    util_type_subparsers.add_parser(REBUILD_CACHE_COMPLETION.tag, help=REBUILD_CACHE_COMPLETION.description)

    return parser


def namespace_to_zsh_completion_args(namespace: argparse.Namespace) -> Optional[CompletionArgs]:
    if namespace.util_type == ZSH_COMPLETION_ITEM.tag:
        return CompletionArgs(
            word_index=namespace.word_index,
            line=namespace.line
        )
    else:
        return None


class ArgCache(FileCache[str, List[ParamValue]]):
    def freeze(self, value: List[ParamValue]) -> str:
        return json.dumps(value)

    def thaw(self, frozen_value: str) -> List[ParamValue]:
        return cast(List[ParamValue], json.loads(frozen_value))

    def freeze_key(self, key: str) -> str:
        return key


def format_post_data(param_args: ArgPairs, initial_post_data: Dict[str, Any]) -> Tuple[List[str], ArgPairs]:
    remaining_argpairs: ArgPairs = []
    post_data = deepcopy(initial_post_data)
    passed_array_params: Set[str] = set()  # needed to correctly overwrite params in the initial_post_data

    for param, arg_value in param_args:
        if param.param_type == ParamType.json_body:
            arg_name = param.name
            if param.type_.is_array:
                if arg_name not in post_data:
                    post_data[arg_name] = [arg_value]
                    passed_array_params.add(arg_name)
                elif arg_name not in passed_array_params:
                    # this means it was in the initial_post_data, and we want to overwrite it
                    post_data[arg_name] = [arg_value]
                    passed_array_params.add(arg_name)
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
    # if --no-requires was passed, there might be some straggling path params that need to be
    # blanks out
    returned_url = re.sub(r'\{.*?\}', '', returned_url)
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


REQUIRES_ARG = ArgParserArg(
    ['-R', '--no-requires'],
    dict(
        action='store_false', dest='use_requires', default=True,
        help='Don\'t check to see if required parameter values are missing or if values are one of the enumerated'
             ' values'
    )
)

BODY_JSON_ARG = ArgParserArg(
    ['-b', '--body-json', '--body'],
    dict(type=json.loads, default={},
         help='Base json object to send in the body.  Required body params are still required unless -R option passed.'
              '  Useful for dealing with incomplete specs.')
)

GENERIC_OPTIONAL_ARGS = [
    ArgParserArg(['-p', '--print-cmd'], dict(action='store_true', default=False,
                                             help='Print the resulting curl command to standard out')),
    ArgParserArg(['-n', '--no-run'], dict(action='store_false', dest='run_cmd', default=True,
                                          help='Don\'t run the curl command.  Useful with -p')),
    REQUIRES_ARG,
    BODY_JSON_ARG
]


def add_generic_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    for arg in GENERIC_OPTIONAL_ARGS:
        parser = arg.add_to_parser(parser)
    return parser


def get_use_requires(words: Sequence[str]) -> bool:
    """
    See's if we have the --no-requires flag set.  Needed before building other args because it's used to determine
    if the args are required
    """
    arg_parser = argparse.ArgumentParser(add_help=False)
    # need to add all the arg-parsers so compound flags ("-npR") get recognized
    arg_parser = add_generic_args(arg_parser)
    args, _ = arg_parser.parse_known_args(words)

    return args.use_requires
