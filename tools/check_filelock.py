"""Real kernel and multi-process checks, including bidirectional Python interop."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _support import source_hash
from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
PACKAGES = BUILD / "packages"
MOJO = Path(sys.executable).parent / "mojo"
WORKER = BUILD / "filelock-worker"
LIVE: list[subprocess.Popen] = []


def run(args, label, timeout=20):
    result = subprocess.run(
        [str(x) for x in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    (BUILD / (label + ".log")).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"{label} failed: " + (result.stdout + result.stderr)[:4000])
    return result.stdout.strip()


def start(mode, lock, *args):
    p = subprocess.Popen(
        [str(WORKER), mode, str(lock), *[str(x) for x in args]],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    LIVE.append(p)
    return p


def finish(p, timeout=10):
    stdout, stderr = p.communicate(timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"worker failed: {stdout} {stderr}")
    return stdout.strip()


def ready(p, marker):
    deadline = time.monotonic() + 5
    while not marker.exists():
        if p.poll() is not None:
            raise RuntimeError("holder exited before ready: " + str(p.communicate()))
        if time.monotonic() > deadline:
            raise TimeoutError("holder readiness timed out")
        time.sleep(0.005)


def kill(p):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGKILL)
    p.communicate(timeout=5)


def low_fd_limit():
    _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    limit = 128 if hard == resource.RLIM_INFINITY else min(128, hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))


def main():
    BUILD.mkdir(exist_ok=True)
    PACKAGES.mkdir(exist_ok=True)
    report = {
        "mojo": run([MOJO, "--version"], "filelock-version"),
        "python_filelock": importlib.metadata.version("filelock"),
        "platform": platform.platform(),
        "scope": "native process tests on the recorded host; remote filesystems unverified",
        "checks": {},
    }
    checks = report["checks"]
    for source, binary in (
        ("filelock_worker", "filelock-worker"),
        ("filelock_contracts", "filelock-contracts"),
        ("readwrite_contracts", "readwrite-contracts"),
        ("held_guard_contracts", "held-guard-contracts"),
        ("process_contracts", "process-contracts"),
    ):
        run(
            [
                MOJO,
                "build",
                "--Werror",
                "-I",
                ROOT / "src",
                ROOT / "tests" / (source + ".mojo"),
                "-o",
                BUILD / binary,
            ],
            binary + "-build",
            120,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="filelock-mojo-") as tmp:
            folder = Path(tmp)
            lock = folder / "coordination.lock"
            checks["native_contracts"] = run(
                [BUILD / "filelock-contracts", folder / "contracts.lock"],
                "filelock-contracts",
            )
            checks["readwrite_contracts"] = run(
                [BUILD / "readwrite-contracts", folder / "readwrite.lock"],
                "readwrite-contracts",
            )
            checks["held_guard_contracts"] = run(
                [BUILD / "held-guard-contracts", folder / "held-guard.lock"],
                "held-guard-contracts",
            )
            rw_readers = []
            for i in range(2):
                marker = folder / f"rw-reader-{i}.ready"
                reader = start("rw_read_hold", lock, marker)
                rw_readers.append(reader)
                ready(reader, marker)
            assert finish(start("rw_read_try", lock)) == "SHARED_ACQUIRED"
            assert finish(start("rw_write_try", lock)) == "BLOCKED"
            kill(rw_readers[0])
            assert finish(start("rw_write_try", lock)) == "BLOCKED"
            kill(rw_readers[1])
            assert finish(start("rw_write_try", lock)) == "ACQUIRED"
            marker = folder / "rw-writer.ready"
            writer = start("rw_write_hold", lock, marker)
            ready(writer, marker)
            assert finish(start("rw_read_try", lock)) == "SHARED_BLOCKED"
            assert finish(start("rw_write_try", lock)) == "BLOCKED"
            kill(writer)
            checks["readwrite_native_process_exclusion"] = "passed"
            readers = []
            for i in range(2):
                marker = folder / f"reader-{i}.ready"
                reader = start("shared_hold", lock, marker)
                readers.append(reader)
                ready(reader, marker)
            assert finish(start("shared_try", lock)) == "SHARED_ACQUIRED"
            assert finish(start("try", lock)) == "BLOCKED"
            kill(readers[0])
            assert finish(start("try", lock)) == "BLOCKED"
            kill(readers[1])
            assert finish(start("try", lock)) == "ACQUIRED"
            exclusive_marker = folder / "exclusive.ready"
            exclusive = start("hold", lock, exclusive_marker)
            ready(exclusive, exclusive_marker)
            assert finish(start("shared_try", lock)) == "SHARED_BLOCKED"
            kill(exclusive)
            checks["shared_readers_exclude_writers"] = "passed"
            checks["exclusive_writer_excludes_readers"] = "passed"
            readonly = folder / "read-only-marker.lock"
            readonly.write_text("retain")
            readonly.chmod(0o400)
            assert finish(start("shared_try", readonly)) == "SHARED_ACQUIRED"
            assert readonly.read_text() == "retain"
            checks["shared_read_only_marker"] = "passed"
            fifo = folder / "fifo-marker.lock"
            os.mkfifo(fifo, 0o600)
            fifo_results = {}
            for mode, flags, operation, message in (
                ("shared_try", os.O_RDONLY, fcntl.LOCK_SH, "SHARED_ACQUIRED"),
                ("try", os.O_RDWR, fcntl.LOCK_EX, "ACQUIRED"),
            ):
                fd = os.open(fifo, flags | os.O_NONBLOCK)
                expected_errno = None
                try:
                    fcntl.flock(fd, operation | fcntl.LOCK_NB)
                except OSError as error:
                    expected_errno = error.errno
                finally:
                    os.close(fd)
                worker = start(mode, fifo)
                stdout, stderr = worker.communicate(timeout=3)
                if expected_errno is None:
                    assert worker.returncode == 0 and stdout.strip() == message
                    fifo_results[mode] = "acquired"
                else:
                    assert worker.returncode != 0 and (
                        f"errno={expected_errno}" in stderr
                    ), (stdout, stderr)
                    fifo_results[mode] = {"kernel_errno": expected_errno}
            checks["fifo_open_without_peer"] = fifo_results
            marker = folder / "held.ready"
            with FileLock(lock, timeout=0):
                assert finish(start("try", lock)) == "BLOCKED"
                timed = finish(start("timeout", lock)).split()
                assert timed[0] == "TIMEOUT" and 0.10 <= float(timed[1]) <= 3, timed
                checks["timeout_seconds"] = float(timed[1])
                result = subprocess.run(
                    [str(WORKER), "many_attempts", str(lock)],
                    capture_output=True,
                    text=True,
                    preexec_fn=low_fd_limit,
                    timeout=10,
                    check=False,
                )
                assert (
                    result.returncode == 0 and result.stdout.strip() == "NO_FD_LEAK"
                ), (result.stdout, result.stderr)
                checks["contended_attempts_under_128_fd_limit"] = 2000
                result = subprocess.run(
                    [str(WORKER), "many_guard_attempts", str(lock)],
                    capture_output=True,
                    text=True,
                    preexec_fn=low_fd_limit,
                    timeout=10,
                    check=False,
                )
                assert (
                    result.returncode == 0
                    and result.stdout.strip() == "NO_GUARD_FD_LEAK"
                ), (result.stdout, result.stderr)
                checks["contended_guard_attempts_under_128_fd_limit"] = 2000
            assert finish(start("try", lock)) == "ACQUIRED"
            checks["python_holder_mojo_contender"] = "passed"
            with FileLock(lock, timeout=0):
                wait_ready = folder / "unbounded.ready"
                waiter = start("wait_default", lock, wait_ready)
                ready(waiter, wait_ready)
                time.sleep(0.05)
                assert waiter.poll() is None, (
                    "Unbounded contender must wait for the holder"
                )
            assert finish(waiter) == "ACQUIRED_AFTER_WAIT"
            checks["unbounded_wait_then_acquire"] = "passed"
            holder = start("hold", lock, marker)
            ready(holder, marker)
            try:
                with FileLock(lock, timeout=0):
                    pass
            except Timeout:
                pass
            else:
                raise AssertionError("Python acquired while native holder was live")
            kill(holder)
            with FileLock(lock, timeout=1):
                pass
            checks["mojo_holder_python_contender_and_kill_cleanup"] = "passed"

            native = json.loads(
                run(
                    [BUILD / "process-contracts", WORKER, folder, lock, 1, 4],
                    "native-process-contracts",
                    timeout=120,
                ).splitlines()[-1]
            )
            assert native == {
                "protected_updates": 480,
                "process_runs": 4,
                "unlocked_negative_control": 1,
            }
            actual = int((folder / "native-counter.txt").read_text())
            lost = int((folder / "native-racy.txt").read_text())
            assert actual == native["protected_updates"] == 480
            assert lost == native["unlocked_negative_control"] == 1
            checks["four_native_workers"] = {
                "increments_per_worker": 120,
                "expected": 480,
                "actual": actual,
            }
            checks["unlocked_negative_control"] = {
                "expected_without_race": 2,
                "observed_lost_update": lost,
            }

            # Preserve the inode and bytes; native code never removes/truncates its marker.
            persistent = folder / "persistent.lock"
            persistent.write_text("keep these bytes")
            inode = persistent.stat().st_ino
            assert finish(start("try", persistent)) == "ACQUIRED"
            assert (
                persistent.read_text() == "keep these bytes"
                and persistent.stat().st_ino == inode
            )
            checks["persistent_marker_identity_and_contents"] = "passed"
            fresh = folder / "private-mode.lock"
            assert finish(start("try", fresh)) == "ACQUIRED"
            assert fresh.stat().st_mode & 0o777 == 0o600
            checks["private_creation_mode"] = "0600"
            symlink = folder / "symlink.lock"
            symlink.symlink_to(persistent)
            result = subprocess.run(
                [str(WORKER), "try", str(symlink)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            assert (
                result.returncode != 0
                and "FileLock system" in result.stderr + result.stdout
            )
            assert persistent.read_text() == "keep these bytes"
            checks["symlink_final_component_rejection"] = "passed"
            missing = folder / "missing" / "lock"
            result = subprocess.run(
                [str(WORKER), "try", str(missing)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            assert result.returncode != 0 and "errno=2" in result.stderr + result.stdout
            checks["filesystem_error_is_not_contention"] = "passed"

            # Exec closes the descriptor even though the replacement process lives on.
            marker = folder / "exec.ready"
            holder = start("exec", lock, marker)
            ready(holder, marker)
            with FileLock(lock, timeout=1):
                assert holder.poll() is None, (
                    "exec process exited instead of remaining alive"
                )
            kill(holder)
            checks["close_on_exec"] = "passed"
            checks["fork_owner_and_child_destructor"] = finish(
                start("fork_check", lock)
            )
            assert checks["fork_owner_and_child_destructor"] == "FORK_OWNER_PRESERVED"

            package = PACKAGES / "filelock_mojo.mojoc"
            run(
                [
                    MOJO,
                    "precompile",
                    "--Werror",
                    ROOT / "src/filelock_mojo",
                    "-o",
                    package,
                ],
                "filelock-package",
                120,
            )
            # Source fixtures are separate from packages, preventing stale adjacent imports.
            sample = folder / "cache.txt"
            checks["compiled_package_example"] = run(
                [
                    MOJO,
                    "run",
                    "--Werror",
                    "-I",
                    PACKAGES,
                    ROOT / "examples/locked_cache.mojo",
                    sample,
                ],
                "filelock-package-example",
                120,
            )
            assert (
                sample.read_text()
                == "Generated while holding a native inter-process lock.\n"
            )
            report["package_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
        for fixture, expected in [
            ("reject_filelock_copy.mojo", "copy"),
            ("reject_filelock_guard_lifetime.mojo", "origin"),
            ("reject_readwrite_copy.mojo", "copy"),
            ("reject_held_guard_copy.mojo", "copy"),
            ("reject_held_guard_lifetime.mojo", "origin"),
            ("reject_readwrite_guard_lifetime.mojo", "origin"),
        ]:
            result = subprocess.run(
                [
                    str(MOJO),
                    "build",
                    "--Werror",
                    "-I",
                    str(ROOT / "src"),
                    str(ROOT / "tests" / fixture),
                    "-o",
                    str(BUILD / "must-not-build"),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            log = result.stdout + result.stderr
            (BUILD / (fixture + ".log")).write_text(log)
            assert result.returncode != 0 and expected in log.lower(), log[:4000]
        checks["copy_and_guard_lifetime_compile_rejections"] = "passed"
        report["source_sha256"] = source_hash("filelock_mojo")
        report["test_harness_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        report["test_source_sha256"] = hashlib.sha256(
            b"".join(
                path.read_bytes() for path in sorted((ROOT / "tests").glob("*.mojo"))
            )
        ).hexdigest()
        (ROOT / "tests/filelock-verification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))
    finally:
        for p in LIVE:
            if p.poll() is None:
                kill(p)


if __name__ == "__main__":
    main()
