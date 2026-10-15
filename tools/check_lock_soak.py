"""Bounded native contention, descriptor pressure and repeated process cleanup."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import resource
import subprocess
import tempfile
import time
from pathlib import Path

from _support import BUILD, MOJO, ROOT, run, source_hash, write_report
from filelock import FileLock


def main():
    executable = BUILD / "lock-soak-worker"
    run(
        [
            MOJO,
            "build",
            "--Werror",
            "-I",
            ROOT / "src",
            ROOT / "tests/filelock_worker.mojo",
            "-o",
            executable,
        ],
        "lock-soak-build",
        timeout=300,
    )
    driver = BUILD / "lock-soak"
    run(
        [
            MOJO,
            "build",
            "--Werror",
            ROOT / "tests/process_contracts.mojo",
            "-o",
            driver,
        ],
        "lock-soak-driver-build",
        timeout=300,
    )
    started = time.monotonic()
    original_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
    hard = original_limit[1]
    try:
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (128 if hard == resource.RLIM_INFINITY else min(128, hard), hard),
        )
        rounds = 12
        workers_per_round = 6
        with tempfile.TemporaryDirectory(prefix="mojo-lock-soak-") as directory:
            root = Path(directory)
            lock = root / "shared.lock"
            live = []
            try:
                native = json.loads(
                    run(
                        [driver, executable, root, lock, rounds, workers_per_round],
                        "lock-soak-native",
                        timeout=300,
                    ).splitlines()[-1]
                )
                expected = rounds * workers_per_round * 120
                assert native == {
                    "protected_updates": expected,
                    "process_runs": rounds * workers_per_round,
                    "unlocked_negative_control": 1,
                }
                assert int((root / "native-counter.txt").read_text()) == expected
                assert int((root / "native-racy.txt").read_text()) == 1
                with FileLock(lock, timeout=2):
                    live = [
                        subprocess.Popen(
                            [str(executable), "many_guard_attempts", str(lock)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                        )
                        for _ in range(6)
                    ]
                    for worker in live:
                        stdout, stderr = worker.communicate(timeout=20)
                        if worker.returncode or stdout.strip() != "NO_GUARD_FD_LEAK":
                            raise RuntimeError(stdout + stderr)
                for index in range(8):
                    ready = root / f"ready-{index}"
                    holder = subprocess.Popen(
                        [str(executable), "hold", str(lock), str(ready)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    live = [holder]
                    deadline = time.monotonic() + 5
                    while not ready.exists():
                        if holder.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("Holder did not become ready")
                        time.sleep(0.005)
                    holder.kill()
                    holder.communicate(timeout=5)
                    with FileLock(lock, timeout=2):
                        pass
            finally:
                for worker in live:
                    if worker.poll() is None:
                        worker.kill()
                    worker.communicate()
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, original_limit)
    report = {
        "status": "passed",
        "protected_updates": expected,
        "process_runs": rounds * workers_per_round,
        "contended_guard_attempts": 12000,
        "descriptor_limit": 128,
        "killed_holders": 8,
        "seconds": time.monotonic() - started,
        "python_filelock": importlib.metadata.version("filelock"),
        "source_sha256": source_hash("filelock_mojo"),
        "driver_sha256": hashlib.sha256(
            (ROOT / "tests/process_contracts.mojo").read_bytes()
        ).hexdigest(),
        "worker_sha256": hashlib.sha256(
            (ROOT / "tests/filelock_worker.mojo").read_bytes()
        ).hexdigest(),
    }
    write_report(ROOT / "tests/lock-soak-verification.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
