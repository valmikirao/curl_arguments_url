#!/usr/bin/env bash

set -ex
set -o pipefail

git diff origin/master -- '*.py' |
  pybugsai --diff-in --cache .pybugsai/cache
