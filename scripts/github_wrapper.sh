#!/usr/bin/env bash

# Wrapper for shell scripts run in github actions.  Does the following:
#   - Uses the setup python virtual environment
#   - Sets `steps.<step-id>.outputs.result to success or fail
#   - Exits with the exit value of the script

set -x  # not doing -e or pipefile

GITHUB_OUTPUT="${GITHUB_OUTPUT:-/dev/stdout}"  # stdout for local testing

. ./scripts/venv_github.sh

"$@"
EXIT_CODE=$?

if [[ $EXIT_CODE == 0 ]]; then
  echo "result=success" >> "$GITHUB_OUTPUT"
else
  echo "result=fail" >> "$GITHUB_OUTPUT"
fi

echo $EXIT_CODE
