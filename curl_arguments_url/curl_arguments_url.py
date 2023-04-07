"""Main module."""
import argparse
import itertools
import json
import os
import re
import shutil
import textwrap
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict
from datetime import datetime
from enum import Enum
from hashlib import md5
from typing import Iterable, NamedTuple, Tuple, Sequence, List, Union, Dict, Optional, TypeVar, Generic, \
    Callable, Any, Set, MutableMapping, cast

from jsonref import replace_refs as replace_json_refs  # type: ignore
from openapi_schema_pydantic import OpenAPI, Operation, RequestBody, Schema, Reference, Parameter, PathItem
from pydantic import BaseModel, validator
from typing_extensions import Literal
from urllib.parse import urlencode

import yaml

REMAINING_ARG = 'passed_to_curl'

ZSH_COMPLETION = 'zsh-completion'
ZSH_PRINT_SCRIPT = 'zsh-print-script'
BASH_COMPLETION = 'bash-completion'
BASH_PRINT_SCRIPT = 'bash-print-script'

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
    description='Directory which contains files for carl.'
)
CARL_DIR = CARL_DIR_ENV.get_value()
OPEN_API_DIR_ENV = EnvVariable(
    'CARL_OPEN_API_DIR', os.path.join(CARL_DIR, 'open_api'),
    description='Directory containing the OpenApi specifications and Yaml files.'
)
OPEN_API_DIR = OPEN_API_DIR_ENV.get_value()
CACHE_DIR_ENV = EnvVariable(
    'CARL_CACHE_DIR', os.path.join(CARL_DIR, 'cache'),
    description='Directory containing the cache.'
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


class ZshCompletionArgs(NamedTuple):
    word_index: int
    line: str

    @classmethod
    def from_namespace(cls, namespace: argparse.Namespace) -> 'ZshCompletionArgs':
        return cls(
            word_index=namespace.word_index,
            line=namespace.line,
        )


class BashCompletionArgs(NamedTuple):
    word_index: int
    line: str
    passed_cwords: List[str]

    @classmethod
    def from_namespace(cls, namespace: argparse.Namespace) -> 'BashCompletionArgs':
        return cls(
            word_index=namespace.word_index,
            line=namespace.line,
            passed_cwords=namespace.passed_cwords
        )


class GenericArgs(NamedTuple):
    print_cmd: bool = False
    run_cmd: bool = False
    util: bool = False
    zsh_completion_args: Optional[ZshCompletionArgs] = None
    zsh_print_script: bool = False
    bash_completion_args: Optional[BashCompletionArgs] = None
    bash_print_script: bool = False

    @classmethod
    def from_namespace(cls, namespace: argparse.Namespace) -> 'GenericArgs':
        if namespace.util_type == ZSH_COMPLETION:
            zsh_completion_args = ZshCompletionArgs.from_namespace(namespace)
        else:
            zsh_completion_args = None

        if namespace.util_type == BASH_COMPLETION:
            bash_completion_args = BashCompletionArgs.from_namespace(namespace)
        else:
            bash_completion_args = None

        return cls(
            util = True,
            zsh_print_script = (namespace.util_type == ZSH_PRINT_SCRIPT),
            bash_print_script = (namespace.util_type == BASH_PRINT_SCRIPT),
            zsh_completion_args=zsh_completion_args,
            bash_completion_args=bash_completion_args

        )

class CompletionItem(NamedTuple):
    tag: str
    description: Optional[str]


UTILS_CMD_STR = 'utils'
UTILS_COMPLETION_ITEM = CompletionItem(UTILS_CMD_STR, 'Utilities')


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

        os.makedirs(OPEN_API_DIR, exist_ok=True)
        if files is None:
            swagger_files = [os.path.join(OPEN_API_DIR, f) for f in os.listdir(OPEN_API_DIR)]
        else:
            swagger_files = files

        if len(swagger_files) == 0:
            # There is no swagger data, but there are some "utils" commands where this is OK
            pass
        else:
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
            no_url_parser = get_arg_parser()
            url_subparsers = no_url_parser.add_subparsers(dest='url', required=True)

            url_subparsers = add_util_parser(url_subparsers)
            for possible_url in possible_urls:
                possible_url_desc = possible_url.description or possible_url.summary
                url_subparsers.add_parser(possible_url.url, help=possible_url_desc)

            # This should give either the correct error or correct help message
            parsed_args = no_url_parser.parse_args(cli_args)

            if parsed_args.url == UTILS_CMD_STR:
                return [], GenericArgs.from_namespace(parsed_args)
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
            method_parser = swagger_endpoint.add_args_from_params(method_parser)

            method_parser.add_argument(REMAINING_ARG, nargs='*', help='Extra argument passed to curl')
        return arg_parser

    def get_completions(self, index: int, words: Sequence[Optional[str]]) -> List[CompletionItem]:
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
            possible_urls = self.root_cache[None].urls
            for possible_url in possible_urls:
                if possible_url.url.lower().startswith(prefix.lower()):
                    description = possible_url.summary or possible_url.description
                    items_to_return.append(CompletionItem(
                        tag=possible_url.url,
                        description=description
                    ))
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

            is_value_arg = self.get_arg_name_this_is_value_for(words_[3:index + 1])
            if is_value_arg is None:
                items_to_return.extend(self.get_param_completions(url, method, prefix=words_[index]))
            else:
                values: List[ArgValue] = arg_value_cache.get(is_value_arg, [])
                prefix = words_[index]
                for value in values:
                    if str(value).lower().startswith(prefix.lower()):
                        items_to_return.append(CompletionItem(
                            tag=str(value),
                            description=None
                        ))
                if len(items_to_return) == 0:
                    # if nothing in the cache matches, return the item itself so it doesn't get blanked out
                    items_to_return = [CompletionItem(tag=prefix, description=None)]
        else:
            items_to_return.append(CompletionItem(
                tag=words_[index],
                description=None
            ))

        return sorted(items_to_return, key=lambda x: x.tag)

    def get_arg_name_this_is_value_for(self, words: List[str]) -> Optional[str]:
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
                    return CarlParam.param_name_from_arg_name(arg)
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


def get_width():
    """ This is what HelpFormatted does for default width """
    try:
        width = int(os.environ['COLUMNS'])
    except (KeyError, ValueError):
        width = 80
    width -= 2

    return width


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
            f"{env_variable.env_name}: {env_variable.description}  Default: {env_variable.default}\n",
            initial_indent=' ' * 4,
            subsequent_indent=' ' * 24
        )
    return return_str


def add_util_parser(parser: Any) -> Any:
    util_parser: argparse.ArgumentParser = parser.add_parser(
        UTILS_COMPLETION_ITEM.tag, description=UTILS_COMPLETION_ITEM.description
    )
    util_type_subparsers = util_parser.add_subparsers(dest='util_type', required=True)

    zsh_completion_parser = util_type_subparsers.add_parser(ZSH_COMPLETION, description='Return completions for zsh')
    zsh_completion_parser.add_argument('word_index', type=int)
    zsh_completion_parser.add_argument('line')

    util_type_subparsers.add_parser(ZSH_PRINT_SCRIPT, description='Print the zsh script that enables completions')

    bash_completion_parser = util_type_subparsers.add_parser(BASH_COMPLETION, description='Return completions for bash')
    bash_completion_parser.add_argument('word_index', type=int)
    bash_completion_parser.add_argument('line')
    bash_completion_parser.add_argument('passed_cwords', nargs='+',
                                        help='Need both these and the line to overcome bash-completions strange'
                                             ' parsing')
    util_type_subparsers.add_parser(BASH_PRINT_SCRIPT, description='Print the bash script that enables completions')

    return parser


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


arg_value_cache = ArgCache('arg_values')


def cache_param_arg_pairs(param_args: ArgPairs) -> None:
    for param, value in param_args:
        key = param.name
        arg_history: List[ArgValue] = arg_value_cache.get(key, [])

        new_history: List[ArgValue] = [value] + [a for a in arg_history if a != value]
        new_history = new_history[:MAX_HISTORY]
        arg_value_cache[key] = new_history


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
