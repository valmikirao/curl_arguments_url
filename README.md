# AWS Cloudwatch Insights

![version](https://img.shields.io/pypi/v/curl_arguments_url)
![python versions](https://img.shields.io/pypi/pyversions/curl_arguments_url)
![build](https://img.shields.io/github/actions/workflow/status/valmikirao/curl_arguments_url/push-workflow.yml?branch=master)

* Free software: Apache Software License 2.0

![demo](https://raw.githubusercontent.com/valmikirao/curl_arguments_url/master/assets/demo.gif)

Though OpenAPI documented services offer a nice UI to test the endpoints, I couldn't find a good command line tool for
this.  Here I created something that works nicely with zsh completions.  If you have the OpenAPI spec available, you
put it in your `~/.carl/open_api`.  Then parameters can be passed as `+{param-name}`, with tab-completions, and then
these are passed to `curl`.

There is no way that this covers all the cases for the OpenAPI spec, but it hopefully covers the vast majority people
of cases people actually encounter.

### Installation

```shell
# globally
% pipx install 'curl_arguments_url'
# or in a particular virtual env
% pip install 'curl_arguments_url'

# to get the completions to work, add the following to your .zshrc
eval "$(carl utils zsh-print-script)"

# And copy the OpenAPI spec into ~/.carl/open_api to get the completions and curl-building working
% cp open_api-spec.yml ~/.carl/open_api
```

### Examples

These examples use [tests/resources/open_api/openapi-demo.yml](tests/resources/open_api/openapi-demo.yml)

* Basic GET

```shell
% carl http://demo.io/v0/entities/\{path-item\} GET +path-item ID +query-item query-this --no-run --print-cmd
curl -X GET 'http://demo.io/v0/entities/ID?query-item=query-this'
```

* More complicated POST command

```shell
% carl http://demo.io/v0/entities/\{path-item\} POST \
    +path-item ID +field-one value +field-two an array of values \
    +field-three '{"complex":["sub","value"]}' \
    +field-header 'Header Param Value' \
    --no-run --print-cmd \
    -- --silent # you can get other arguments passed to curl at the end, like this
# the output wouldn't be this nicely formatted, but so you can see what curl command would be run
curl -X POST http://demo.io/v0/entities/ID \
  -H 'field-header: Header Param Value' -H 'Content-Type: application/json' \
  --data-binary \
  '{"field-one": "value", "field-two": ["an", "array", "of", "values"], "field-three": {"complex": ["sub", "value"]}}' \
  --silent
 ```

* Values are cached for completion by param name.

![demo](https://raw.githubusercontent.com/valmikirao/curl_arguments_url/master/assets/demo-value-completions.gif)

* These cached values can be managed with the `carl utils cached-values` utility:

```shell
% carl utils cached-values --help
usage: carl utils cached-values [-h] {params,ls,rm,add} ...

positional arguments:
  {params,ls,rm,add}
    params            List all the param names that have values cached
    ls                List all the values cached for a particular param
    rm                Remove a value for an param from the cache for completions
    add               Add one or more values for a param to the cache

options:
  -h, --help          show this help message and exit
```

* Help is generated from the OpenAPI spec for your reference

```text
% carl --help
usage: carl [-h] {utils,http://demo.io/v0/entities/{path-item},http://demo.io/v0/restricted,http://demo.io/v0/other,http://demo.io/v0/endpoints} ...

A Utility to cleanly take command-line arguments, for an endpoint you have the
OpenAPI specification for, and convert them into an appropriate curl command.
Spec files should be in /root/.carl/open_api directory or directory defined by
env variables (See below)

positional arguments:
  {utils,http://demo.io/v0/entities/{path-item},http://demo.io/v0/restricted,http://demo.io/v0/other,http://demo.io/v0/endpoints}
    utils               Utilities
    http://demo.io/v0/entities/{path-item}
                        Demo Entity Endpoint
    http://demo.io/v0/restricted
                        A Restricted Endpoint
    http://demo.io/v0/other
                        Another Endpoint
    http://demo.io/v0/endpoints
                        Yet Another Endpoint

options:
  -h, --help            show this help message and exit

Environment Variables:
    CARL_DIR: Directory which contains files for carl. Default: ~/.carl
    CARL_OPEN_API_DIR: Directory containing the OpenApi specifications and
                        Yaml files. Default: $CARL_DIR/open_api
    CARL_CACHE_DIR: Directory containing the cache. Default $CARL_DIR/cache
```

For a specific endpoint:
```text
% carl http://demo.io/v0/entities/\{path-item\} POST --help
usage: carl http://demo.io/v0/entities/{path-item} POST [-h] [-p] [-n] [-R] [-b BODY_JSON] [+field-header FIELD_HEADER] [+field-one FIELD_ONE]
                                                        [+field-two FIELD_TWO [FIELD_TWO ...]] [+field-three FIELD_THREE] +path-item PATH_ITEM
                                                        [passed_to_curl ...]

Demo Post Command

positional arguments:
  passed_to_curl        Extra argument passed to curl, often after "--"

options:
  -h, --help            show this help message and exit
  -p, --print-cmd       Print the resulting curl command to standard out
  -n, --no-run          Don't run the curl command. Useful with -p
  -R, --no-requires     Don't check to see if required parameter values are missing or if values are one of the enumerated values
  -b BODY_JSON, --body-json BODY_JSON, --body BODY_JSON
                        Base json object to send in the body. Required body params are still required unless -R option passed. Useful for dealing with incomplete specs.
  +field-header FIELD_HEADER
                        Header Param
  +field-one FIELD_ONE  Demo Body String Field
  +field-two FIELD_TWO [FIELD_TWO ...]
                        Demo Body Array Field
  +field-three FIELD_THREE
                        Demo Body Complex Field
  +path-item PATH_ITEM
```

* Generic Optional Args:

```text
  -p, --print-cmd       Print the resulting curl command to standard out
  -n, --no-run          Don't run the curl command. Useful with -p
  -R, --no-requires     Don't check to see if required parameter values are missing or if values are one of the enumerated values
  -b BODY_JSON, --body-json BODY_JSON, --body BODY_JSON
                        Base json object to send in the body. Required body params are still required unless -R option passed. Useful for dealing with incomplete specs.
```

* Relevant Environment Variables

```text
    CARL_DIR: Directory which contains files for carl. Default: ~/.carl
    CARL_OPEN_API_DIR: Directory containing the OpenApi specifications and
                        Yaml files. Default: $CARL_DIR/open_api
    CARL_CACHE_DIR: Directory containing the cache. Default $CARL_DIR/cache
```


## Development

Requires make:

```shell
# setting up dev environment
$ make develop

# run tests
$ make test
# ... or
$ pytest

# run tests for all environments
$ make test-all

```

No CI/CD or coverage yet

## To Do/Future Features

* A `--query` option for adding query parameters directly
* Some sort of hook infrastructure, so you could do things like have custom-completions for certain parameters or
    automatically add a particular env variable as an auth header
* Support file uploading and downloading
* Utilize the authorization part of the OpenAPI spec
* Better support for nested json objects in the body, so that `+param.sub-param value` would set
    `{"param"{"sub-param":"value"}}`
* Maybe support older versions of Swagger/OpenApi
* Speaking of which, in the code I sometimes use the term "swagger" and sometimes "open_api".  I should make this
    consistent.
* Support bash and fish.  With how I implemented this, I thought it would be easy to implement bash.  But the way bash
    parses and escapes arguments passed to the completion function made it surprisingly challenging.  The
    `bash-completion` branch has my so-far attempts to deal with these issues.  It might be close to done, or there
    might be a slew of other issues I haven't realized yet.

## Credits

This package was created with _cookiecutter_ and the `audreyr/cookiecutter-pypackage` project template.
