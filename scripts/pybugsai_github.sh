#!/usr/bin/env bash

set -ex
set -o pipefail

exit 1

git ls-files '*.py' |
  pybugsai --in --cache .pybugsai/cache --abs-max-chunk-size 1000 --strict-chunk-size
