"""Process-test worker; all writes are to harness-supplied temporary paths."""
from std.sys import argv
from std.time import sleep, perf_counter
from std.ffi import external_call, c_int, c_char
from std.collections import Optional
from std.memory import Pointer
from std.origin import ImmUntrackedOrigin
from std.os.path import exists
from filelock_mojo import FileLock, ReadWriteLock


def signal_ready(path: String) raises:
    with open(path, "w") as f:
        f.write("ready")


def increment(path: String) raises:
    var value: Int
    with open(path, "r") as f:
        var text = f.read()
        value = Int(external_call["atoi", c_int](text.as_c_string_span()))
    sleep(0.0001)  # Force a real read/modify/write contention opportunity.
    with open(path, "w") as f:
        f.write(String(value + 1))


def main() raises:
    var args = argv()
    if len(args) < 3:
        raise Error("MODE LOCK_PATH [DATA/READY_PATH]")
    var mode = args[1]
    var path = args[2]
    if mode == "rw_read_try":
        var lock = ReadWriteLock(path)
        if lock.try_acquire_read():
            print("SHARED_ACQUIRED")
            lock.release()
        else:
            print("SHARED_BLOCKED")
    elif mode == "rw_write_try":
        var lock = ReadWriteLock(path)
        if lock.try_acquire_write():
            print("ACQUIRED")
            lock.release()
        else:
            print("BLOCKED")
    elif mode == "rw_read_hold":
        var lock = ReadWriteLock(path, timeout=2)
        with lock.read():
            signal_ready(args[3])
            sleep(30)
    elif mode == "rw_write_hold":
        var lock = ReadWriteLock(path, timeout=2)
        with lock.write():
            signal_ready(args[3])
            sleep(30)
    elif mode == "try":
        var lock = FileLock(path)
        if lock.try_acquire():
            print("ACQUIRED")
            lock.release()
        else:
            print("BLOCKED")
    elif mode == "shared_try":
        var lock = FileLock(path, mode=.shared)
        if lock.try_acquire():
            print("SHARED_ACQUIRED")
            lock.release()
        else:
            print("SHARED_BLOCKED")
    elif mode == "shared_hold":
        with FileLock(path, timeout=2, mode=.shared):
            signal_ready(args[3])
            sleep(30)
    elif mode == "wait_default":
        signal_ready(args[3])
        with FileLock(path):
            print("ACQUIRED_AFTER_WAIT")
    elif mode == "timeout":
        var lock = FileLock(path, timeout=0.15, poll_interval=0.005)
        var start = perf_counter()
        try:
            lock.acquire()
        except e:
            if "timeout" not in String(e):
                raise e^
            print("TIMEOUT", perf_counter() - start)
            return
        raise Error("Contender unexpectedly acquired")
    elif mode == "hold":
        with FileLock(path, timeout=2):
            signal_ready(args[3])
            sleep(30)
    elif mode == "counter":
        var lock = FileLock(path, timeout=5, poll_interval=0.001)
        for _ in range(120):
            with lock.hold():
                increment(args[3])
        print("COUNTER_DONE")
    elif mode == "many_guard_attempts":
        var lock = FileLock(path)
        for _ in range(2000):
            var attempted = lock.try_hold()
            if attempted:
                raise Error("Contender unexpectedly acquired")
        print("NO_GUARD_FD_LEAK")
    elif mode == "many_attempts":
        var lock = FileLock(path)
        for _ in range(2000):
            if lock.try_acquire():
                raise Error("Contender unexpectedly acquired")
        print("NO_FD_LEAK")
    elif mode == "racy":
        # Deterministically force two unprotected workers to read the same old
        # value before either writes it. The harness controls the common gate.
        var value: Int
        with open(args[3], "r") as f:
            var text = f.read()
            value = Int(external_call["atoi", c_int](text.as_c_string_span()))
        signal_ready(args[4])
        var deadline = perf_counter() + 10
        while not exists(args[5]):
            if perf_counter() > deadline:
                raise Error("Unprotected-worker gate timed out")
            sleep(0.001)
        with open(args[3], "w") as f:
            f.write(String(value + 1))
    elif mode == "exec":
        with FileLock(path, timeout=2):
            signal_ready(args[3])
            var command = String("/bin/sleep")
            var arg0 = String("sleep")
            var arg1 = String("2")
            var end: Optional[Pointer[c_char, ImmUntrackedOrigin]] = None
            _ = external_call["execl", c_int, num_fixed_args=2](
                command.as_c_string_span(),
                arg0.as_c_string_span(),
                arg1.as_c_string_span(),
                end,
            )
            raise Error("exec failed")
    elif mode == "fork_check":
        var lock = FileLock(path, timeout=2)
        lock.acquire()
        var child = external_call["fork", c_int]()
        if child < 0:
            raise Error("fork failed")
        if child == 0:
            var rejected = False
            try:
                lock.release()
            except e:
                rejected = "another process" in String(e)
            (lock^).__deinit__()
            _ = external_call["_exit", NoneType](c_int(0 if rejected else 1))
            return
        var status: c_int = -1
        var waited = external_call["waitpid", c_int](
            child, Pointer(to=status), c_int(0)
        )
        if waited != child or status != 0:
            raise Error("child ownership check failed")
        var rival = FileLock(path)
        if rival.try_acquire():
            raise Error("child cleanup unlocked parent")
        lock.release()
        print("FORK_OWNER_PRESERVED")
    else:
        raise Error("Unknown worker mode")
