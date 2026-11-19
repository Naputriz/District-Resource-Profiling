#!/usr/bin/env python3
"""
District Resource Profiling - Test Suite Runner.
Executes testing pyramid levels: unit, integration, system, or all.

Usage:
    python run_all_tests.py --unit
    python run_all_tests.py --integration
    python run_all_tests.py --system
    python run_all_tests.py --all
    python run_all_tests.py --all --report
"""

import argparse
import os
import sys
import time
import subprocess


def parse_args():
    parser = argparse.ArgumentParser(
        description="Unified test suite runner for District Resource Profiling."
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--unit", action="store_true", help="Run Unit tests (offline, pure logic)")
    group.add_argument("--integration", action="store_true", help="Run Integration tests (PostGIS + Redis)")
    group.add_argument("--system", action="store_true", help="Run System tests (API, UI, Chat)")
    group.add_argument("--all", action="store_true", help="Run entire test pyramid (unit + integration + system)")

    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate JUnit XML and HTML coverage reports in test-reports/",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose pytest output",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    reports_dir = os.path.abspath("test-reports")
    if args.report:
        os.makedirs(reports_dir, exist_ok=True)

    pytest_cmd = [sys.executable, "-m", "pytest"]
    if args.verbose:
        pytest_cmd.append("-v")

    # Select target path / markers
    targets = []
    if args.unit:
        targets = ["backend/tests/unit"]
    elif args.integration:
        targets = ["backend/tests/integration"]
    elif args.system:
        targets = ["backend/tests/system"]
    elif args.all:
        targets = [
            "backend/tests/unit",
            "backend/tests/integration",
            "backend/tests/system",
        ]
    else:
        # Default target set: unit + integration
        targets = [
            "backend/tests/unit",
            "backend/tests/integration",
        ]

    cmd = list(pytest_cmd) + targets

    if args.report:
        xml_path = os.path.join(reports_dir, "junit.xml")
        html_dir = os.path.join(reports_dir, "coverage")
        cmd.extend([
            f"--junitxml={xml_path}",
            "--cov=backend/app",
            "--cov=watchdog",
            f"--cov-report=html:{html_dir}",
            "--cov-report=term-missing",
        ])

    print("=" * 70)
    print(" District Resource Profiling - Test Execution")
    print(f" Targets: {', '.join(targets)}")
    if args.report:
        print(f" Reports: {reports_dir}")
    print("=" * 70)

    start_time = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - start_time

    print("=" * 70)
    print(f" Execution completed in {elapsed:.2f} seconds with exit code: {result.returncode}")
    if args.report:
        print(f" JUnit XML: {os.path.join(reports_dir, 'junit.xml')}")
        print(f" Coverage HTML: {os.path.join(reports_dir, 'coverage', 'index.html')}")
    print("=" * 70)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
