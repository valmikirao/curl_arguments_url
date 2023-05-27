#!/usr/bin/env bash

set -ex
set -o pipefail

git diff origin/master -- '*.py' |
  python -m py_bugs_open_ai.cli --diff-in --cache .pybugsai/cache
