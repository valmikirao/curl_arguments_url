import json
from typing import Dict, Any

import jsonref
import yaml
from pyswagger import App
import jsonschema
from openapi_schema_pydantic import OpenAPI, Operation, PathItem

from curl_arguments_url.models import swagger_1


def _slurp_json(file: str) -> Dict[str, Any]:
    with open(file, "r") as f:
        file_data = json.load(f)
        return file_data


def _slurp_yaml(file: str) -> Dict[str, Any]:
    with open(file, "r") as f:
        file_data = yaml.safe_load(f)
        assert file_data
        # _prune_empty_dict_values(file_data)
        return file_data


def _prune_empty_dict_values(value: Any):
    if isinstance(value, dict):
        dict_items = list(value.items())
        for dict_key, dict_value in dict_items:
            if dict_value is None or dict_value in ([], {}):
                del value[dict_key]
            else:
                _prune_empty_dict_values(dict_value)
    elif isinstance(value, list):
        for list_value in value:
            _prune_empty_dict_values(list_value)


def _make_all_values_str(value: Any) -> Any:
    if isinstance(value, list):
        return [_make_all_values_str(v) for v in value]
    elif isinstance(value, dict):
        return {k: _make_all_values_str(v) for k, v in value.items()}
    else:
        return str(value)


# OpenAPI.update_forward_refs()
# Operation.update_forward_refs({'PathItem': PathItem})


def main(file: str):
    # App.create(file)
    if file.endswith(".json"):
        file_data = _slurp_json(file)
    elif file.endswith(".yml") or file.endswith(".yaml"):
        file_data = _slurp_yaml(file)
    else:
        raise NotImplementedError()

    try:
        replace_refs_data = jsonref.replace_refs(file_data, merge_props=True)
        parsed_data = OpenAPI.parse_obj(replace_refs_data)
        print(file + ": " + parsed_data.json()[:100])
    except Exception as e:
        print(f"Problem with {file!r}: {e}")

    # swagger_json_schema = _slurp_json('resources/swagger-2.0-scratch.spec.json')

    # for spec in file_data['paths'].values():
    #     for method_spec in spec.values():
    #         responses = method_spec.get('responses') or {}
    #         response_items = list(responses.items())
    #         for code, resp_spec in response_items:
    #             responses[str(code)] = resp_spec
    #             del responses[code]

    # result = jsonschema.validate(instance=file_data, schema=swagger_json_schema)

    # print(result)


FILES = [
    "/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/link-example.yaml",
    "/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/api-with-examples.yaml",
    "/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/petstore-expanded.yaml",
    "/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/uspto.yaml",
    # '/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/callback-example.yaml',
    "/Users/valmikirao/Dropbox/git/OpenAPI-Specification/examples/v3.0/petstore.yaml",
]


if __name__ == "__main__":
    # file = '/Users/valmikirao/tmp/tmp.json'
    # file = 'tests/resources/swagger/customer_code.yml'
    # file = '/Users/valmikirao/tmp/swapi.1.0.0.json'
    # file = 'tests/resources/swagger/swapi-swagger.yml'
    # file = 'https://api.swaggerhub.com/apis/ahardia/swapi/1.0.0'
    # file = 'tests/resources/swagger/swapi.1.0.0-2.yml'
    file = "tests/resources/swagger/ox_securities.yml"
    main(file)
    # for file in FILES:
    #     main(file)
