import os
import re
from hashlib import md5
from typing import List
from urllib.parse import urlparse

import requests
import yaml

SWAGGER_DIR = None


def get_filename_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    domain_path = parsed_url.netloc + parsed_url.path
    url_alphanum = re.sub(r"\W", "_", domain_path)
    md5_suffix = md5(url.encode()).hexdigest()[:16]

    return os.path.join(SWAGGER_DIR, f"{url_alphanum}-{md5_suffix}.yml")


def fetch_swagger(url: str) -> None:
    response = requests.get(url)
    response.raise_for_status()
    response_data = response.json()

    if "apis" in response_data:
        for api in response_data["apis"]:
            for prop in api.get("properties", []):
                if prop.get("type") == "Swagger" and "url" in prop:
                    fetch_swagger(prop["url"])
    elif "paths" in response_data:
        with open(get_filename_from_url(url), "w") as f:
            yaml.dump(response_data, stream=f)

        scheme = response_data["schemes"][0]
        host = response_data["host"]
        base_path = response_data["basePath"]

        base_for_paths = f"{scheme}://{host}/{base_path}"

        for path in response_data["paths"]:
            pass

    else:
        raise NotImplementedError()

    print(response)


if __name__ == "__main__":
    "testing only"
    fetch_swagger("https://api.swaggerhub.com/apis/ahardia/swapi")
