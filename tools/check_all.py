"""Run the complete source and compiled-package acceptance suite."""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
import time

from _support import (
    MOJO,
    PACKAGE_NAMES,
    ROOT,
    run,
    source_hash,
    source_manifest,
    verification_manifest,
    write_report,
)

CHECKS = [
    "check_api.py",
    "check_filelock.py",
    "check_atomic.py",
    "check_lock_soak.py",
    "check_docs.py",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="local")
    args = parser.parse_args()
    if not args.report.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Report label must be alphanumeric")
    started = time.perf_counter()
    verified_inputs = verification_manifest()
    run([sys.executable, "-m", "ruff", "check", ROOT / "tools"], "lint")
    run(
        [sys.executable, "-m", "ruff", "format", "--check", ROOT / "tools"],
        "python-format",
    )
    results = {}
    for script in CHECKS:
        print(f"Running {script}", flush=True)
        stamp = time.perf_counter()
        output = run(
            [sys.executable, ROOT / "tools" / script],
            args.report + "-" + script,
            timeout=1800,
        )
        results[script] = {
            "status": "passed",
            "seconds": time.perf_counter() - stamp,
            "stdout_sha256": hashlib.sha256(output.encode()).hexdigest(),
        }
        print(output, flush=True)
    if verification_manifest() != verified_inputs:
        raise RuntimeError(
            "Source, tests or configuration changed while checks were running"
        )
    report = {
        "status": "passed",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "mojo": run([MOJO, "--version"], "all-version"),
        "checks": results,
        "seconds": time.perf_counter() - started,
        "verified_inputs": verified_inputs,
        "packages": {
            name: {"source_sha256": source_hash(name), "files": source_manifest(name)}
            for name in PACKAGE_NAMES
        },
    }
    destination = ROOT / "tests" / ("acceptance-" + args.report + ".json")
    write_report(destination, report)
    print(f"Acceptance report: {destination}", flush=True)


if __name__ == "__main__":
    main()
