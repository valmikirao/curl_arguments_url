from enum import Enum
from typing import List


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
