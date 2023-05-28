#!/usr/bin/env bash

set -ex
set -o pipefail

git ls-files '*.py' |
  pybugsai --in --cache .pybugsai/cache
