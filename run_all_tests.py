#!/usr/bin/env python3
"""
Master Test Verification Suite for District Resource Profiling.
Thin wrapper calling pytest (README.md §17).
Supports pytest arguments, e.g.:
    python run_all_tests.py -m unit
    python run_all_tests.py -m db
    python run_all_tests.py
"""

import sys
import pytest


def main():
    args = sys.argv[1:]
    if not args:
        args = ["-v"]
    print(f"Running pytest with args: {args}", flush=True)
    exit_code = pytest.main(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
