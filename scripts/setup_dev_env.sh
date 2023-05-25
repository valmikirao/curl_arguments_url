#!/usr/bin/env bash

set -ex
set -o pipefail

pip install -e .

PYTHON_VERSION="$(python --version)"
if [[ "$PYTHON_VERSION" == "Python 3.7."* ]]; then
  echo 'Python Version > 3.8 required to run pybugsai' >&2
  pip install -r requirements_dev.txt
else
  pip install -r requirements_dev.txt -r requirements_pybugsai.txt
fi
