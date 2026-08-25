#!/usr/bin/env python3
"""Aggregate test runner for the lf-report-render service (CI entry point).

Usage: python3 scripts/test-lf-report.py
Runs the full pytest suite from the service directory (module imports are
path-relative) and exits with pytest's status.
"""
import os
import subprocess
import sys

SERVICE = os.path.join(os.path.dirname(__file__), "..", "services", "lf-report-render")

if __name__ == "__main__":
    sys.exit(subprocess.call(
        [sys.executable, "-m", "pytest", "tests/", "-q", *sys.argv[1:]],
        cwd=os.path.abspath(SERVICE)))
