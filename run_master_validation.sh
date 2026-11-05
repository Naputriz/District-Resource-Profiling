#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
python3 run_all_tests.py "$@" < /dev/null
