import traceback
from urllib.parse import parse_qs

import flask
from flask import Flask

app = Flask(__name__)


@app.route('/<path:path>', methods=['GET', 'POST'])
def hello_world(path: str):
    try:
        return_dict = {'path': path}
        if flask.request.query_string:
            return_dict['query'] = parse_qs(flask.request.query_string.decode())
        if flask.request.content_type == 'application/json':
            return_dict['json_body'] = flask.request.json
        headers = dict(flask.request.headers)
        # get rid of generit headers
        del headers['Accept'], headers['Host'], headers['User-Agent']
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
