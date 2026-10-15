"""Verify real atomic publication, contention, killed writers and bounded reads."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from _support import BUILD, MOJO, ROOT, run, source_hash, write_report


def main():
    worker = BUILD / "atomic-worker"
    run(
        [
            MOJO,
            "build",
            "--Werror",
            "-I",
            ROOT / "src",
            ROOT / "tests/atomic_worker.mojo",
            "-o",
            worker,
        ],
        "atomic-build",
    )
    with tempfile.TemporaryDirectory(prefix="atomic-check-", dir=BUILD) as folder:
        work = Path(folder)
        target = work / "checkpoint with spaces.txt"

        def command(mode, path=target, value=""):
            return [str(worker), mode, str(path), value]

        def invoke(mode, path=target, value="", success=True):
            result = subprocess.run(
                command(mode, path, value),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert (result.returncode == 0) == success, (result.stdout, result.stderr)
            return result.stdout.rstrip("\n")

        values = [
            f"writer={i}; héllø 世界\n" + (str(i) + ";") * 4096 for i in range(48)
        ]
        initial = "previous complete checkpoint\n"
        invoke("write", value=initial)
        marker = target.with_name(target.name + ".lock")
        inode = marker.stat().st_ino
        assert target.stat().st_mode & 0o777 == 0o600
        assert invoke("read", value=str(len(initial.encode()))) == initial.rstrip("\n")
        invoke("read", value="1", success=False)
        invoke("read", value="-1", success=False)
        invoke("write", path="", value="bad", success=False)
        directory = work / "directory"
        directory.mkdir()
        invoke("write", path=directory, value="never published", success=False)
        assert not list(work.glob("*.tmp-*"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(invoke, "write", target, value) for value in values]
            observed = set()
            while not all(f.done() for f in futures):
                # This reader deliberately ignores the advisory lock. Atomic rename
                # must still expose only an entire old or new file.
                current = target.read_text()
                assert current in {initial, *values}
                observed.add(hashlib.sha256(current.encode()).hexdigest())
            for future in futures:
                future.result()
        assert target.read_text() in values
        invoke("write", value=initial)
        child = subprocess.Popen(
            command("large"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while not list(work.glob(target.name + ".tmp-*")):
                assert child.poll() is None, child.communicate()
                if time.monotonic() > deadline:
                    raise TimeoutError("Writer never reached its private temporary")
                time.sleep(0.001)
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate(timeout=10)
            assert child.returncode == -signal.SIGKILL
            assert target.read_text() == initial
            orphans = len(list(work.glob(target.name + ".tmp-*")))
            invoke("write", value="recovered")
            assert invoke("read", value="9") == "recovered"
            assert marker.stat().st_ino == inode
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate(timeout=10)
        report = {
            "status": "passed",
            "source_sha256": source_hash("filelock_mojo"),
            "writers": len(values),
            "concurrent_reader_complete_files": True,
            "observed_versions": len(observed),
            "killed_writer_preserved_previous": True,
            "orphan_temporaries_after_kill": orphans,
            "recovery": True,
            "stable_marker_inode": True,
            "failed_rename_cleanup": True,
            "bounded_utf8_reads": True,
            "private_permissions": True,
            "durability": "file synced; directory/power-loss durability not promised",
        }
        write_report(ROOT / "tests/atomic-verification.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
