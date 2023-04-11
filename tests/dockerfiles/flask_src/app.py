import traceback
from enum import Enum
from urllib.parse import parse_qs

import flask
from flask import Flask

app = Flask(__name__)


class Method(Enum):
    # unfortunate copy-pasta from curl_arguments_url.py, but that code
    # is not available here
    GET = 'GET'
    PUT = 'PUT'
    POST = 'POST'
    DELETE = 'DELETE'
    OPTIONS = 'OPTIONS'
    HEAD = 'HEAD'
    PATCH = 'PATCH'
    TRACE = 'TRACE'


@app.route('/<path:path>', methods=list(Method.__members__.keys()))
def hello_world(path: str):
    try:
        return_dict = {
            'path': path,
            'method': flask.request.method
        }
        if flask.request.query_string:
            return_dict['query'] = parse_qs(flask.request.query_string.decode())
        if flask.request.content_type == 'application/json':
            return_dict['json_body'] = flask.request.json
        headers = dict(flask.request.headers)
        # get rid of generic headers
        for header in ('Accept', 'Host', 'User-Agent', 'Content-Length', 'Content-Type'):
            if header in headers:
                del headers[header]
        if headers:
            return_dict['extra_headers'] = headers
        return flask.jsonify(return_dict)
    except:  # noqa: E722
        stack_trace = traceback.format_exc()
        return flask.jsonify({
            "error": True,
            "stack_trace": stack_trace,
            # "partial_return_dict": return_dict
        }), 400
