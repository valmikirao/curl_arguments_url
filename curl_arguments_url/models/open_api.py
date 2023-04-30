from typing import Optional, Dict, List, Any, Iterable, Tuple, Union

from pydantic import BaseModel, ValidationError, Field, validator

from curl_arguments_url.models.methods import METHODS


class CarlBaseModel(BaseModel):
    class Config(BaseModel.Config):
        allow_population_by_field_name = True


class Info(CarlBaseModel):
    title: str = ''
    summary: Optional[str] = None
    description: Optional[str] = None


class ServerVariable(CarlBaseModel):
    enum: Optional[List[str]] = None
    description: Optional[str] = None
    default: Optional[str] = None


class Server(CarlBaseModel):
    url: str
    variables: Optional[Dict[str, ServerVariable]] = None


class Schema(CarlBaseModel):
    description: Optional[str] = None
    # maybe convert `type` to an enum at some point
    type: Optional[Union[str, List[str]]] = None
    items: Optional['Schema'] = None
    required: Optional[List[str]] = None
    properties: Optional[Dict[str, 'Schema']] = None
    enum: Optional[List[Any]] = Field(default=None, min_items=1)

    @validator('required', pre=True)
    def validate_required(cls, v):
        if isinstance(v, bool):
            # this will be handled by .validate_properties()
            return None
        else:
            return v

    @validator('properties', pre=True)
    def validate_properties(cls, v, values):
        """
        As far as I can tell, "required" should never be a bool, but some schemas (I'm looking at you, athenahealth!)
        do this.  Assume it means that the property should be in the parent schema's "required" array
        """
        if isinstance(v, dict):
            for prop, schema in v.items():
                if isinstance(schema, dict):
                    if isinstance(schema.get('required'), bool) and schema['required']:
                        if values.get('required') is None:
                            values['required'] = []
                        values['required'].append(prop)
                else:
                    raise NotImplementedError('Not parsing anything else yet')
            return v
        elif v is None:
            return None
        else:
            raise AssertionError('Must be a dict or None')


class Parameter(CarlBaseModel):
    name: str
    description: Optional[str] = None
    param_in: str = Field(alias="in")
    required: bool = False
    param_schema: Optional[Schema] = Field(default=None, alias="schema")


class MediaType(CarlBaseModel):
    media_type_schema: Optional[Schema] = Field(default=None, alias="schema")


class RequestBody(CarlBaseModel):
    content: Dict[str, MediaType]


class Operation(CarlBaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None
    servers: Optional[List[Server]] = None
    parameters: Optional[List[Parameter]] = None
    requestBody: Optional[RequestBody] = None


class PathItem(CarlBaseModel):
    servers: Optional[List[Server]] = None
    description: Optional[str] = None
    summary: Optional[str] = None

    get: Optional[Operation] = None
    put: Optional[Operation] = None
    post: Optional[Operation] = None
    delete: Optional[Operation] = None
    options: Optional[Operation] = None
    head: Optional[Operation] = None
    patch: Optional[Operation] = None
    trace: Optional[Operation] = None


class OpenApiLazy(CarlBaseModel):
    """
    This replaces Kuimono's openapi-schema-pydantic, which I used before and still has my appreciation.  This, however,
    only parses the part of the model we care about, making it more robust
    """

    info: Info
    servers: List[Server] = Field(default_factory=lambda: [Server(url="/")])

    unparsed_paths: Dict[str, Any] = {}

    def get_lazy_paths(self, warnings: bool) -> Iterable[Tuple[str, PathItem]]:
        for unparsed_path, unparsed_path_item in self.unparsed_paths.items():
            for method_ in METHODS:
                method = method_.lower()
                operation = unparsed_path_item.get(method)
                if operation is not None:
                    operation.pop('responses', None)
            try:
                yield unparsed_path, PathItem.parse_obj(unparsed_path_item)
            except ValidationError as e:
                if warnings:
                    print(f"Warning: Error in parsing path {unparsed_path!r}: {str(e)}")
