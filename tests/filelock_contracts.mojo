"""Native lock ownership, nesting, cleanup and rejected-argument contracts."""
from std.sys import argv
from std.testing import assert_equal, assert_true
from filelock_mojo import FileLock, LockMode


def try_acquire(mut lock: FileLock) raises -> Bool:
    return lock.try_acquire()


def return_early(mut lock: FileLock) raises -> Int:
    with lock.hold(timeout=0):
        return 7


def main() raises:
    var args = argv()
    if len(args) != 2:
        raise Error("pass an isolated test lock path")
    var path = args[1]
    var owner = FileLock(path, timeout=0)
    var rival = FileLock(path, timeout=0)
    assert_true(not owner.is_locked())
    assert_true(try_acquire(owner))
    assert_true(try_acquire(owner))
    assert_equal(owner.lock_count(), 2)
    assert_true(not try_acquire(rival))
    owner.release()
    assert_equal(owner.lock_count(), 1)
    assert_true(not try_acquire(rival))
    owner.release()
    assert_true(try_acquire(rival))
    rival.release()
    var rejected = False
    try:
        owner.release()
    except e:
        rejected = "not held" in String(e)
    assert_true(rejected)
    assert_true(try_acquire(owner))
    var moved = owner^
    assert_true(moved.is_locked())
    assert_true(not try_acquire(rival))
    moved.release()

    try:
        with moved.hold(timeout=0):
            assert_true(not try_acquire(rival))
            raise Error("body failure")
    except e:
        rejected = String(e) == "body failure"
    assert_true(rejected and not moved.is_locked())
    assert_true(try_acquire(rival))
    rival.release()
    assert_equal(return_early(moved), 7)
    assert_true(not moved.is_locked())
    for i in range(2):
        with moved.hold():
            if i == 0:
                continue
            break
    assert_true(not moved.is_locked())
    with FileLock(path, timeout=0):
        assert_true(not try_acquire(rival))
    assert_true(try_acquire(rival))
    rival.release()

    var guard = moved.hold(timeout=0)
    guard.__enter__()
    rejected = False
    try:
        guard.__enter__()
    except e:
        rejected = "entered twice" in String(e)
    assert_true(rejected)
    guard.__exit__()
    assert_true(not moved.is_locked())

    assert_true(try_acquire(moved))
    var inactive = moved.hold(timeout=0)
    rejected = False
    try:
        inactive.__exit__()
    except e:
        rejected = "entered before exit" in String(e)
    assert_true(rejected)
    assert_true(
        not try_acquire(rival),
        "inactive guard must not release another acquisition",
    )
    moved.release()

    for bad in [Float64(-2), Float64(0) / Float64(0), Float64(1) / Float64(0)]:
        rejected = False
        try:
            moved.acquire(timeout=bad)
        except e:
            rejected = "invalid timeout" in String(e)
        assert_true(rejected and not moved.is_locked())
    for bad in [
        Float64(0),
        Float64(-1),
        Float64(0) / Float64(0),
        Float64(1) / Float64(0),
    ]:
        rejected = False
        try:
            var invalid = FileLock(path, poll_interval=bad)
        except e:
            rejected = "invalid timeout" in String(e)
        assert_true(rejected)
    for bad in [String(""), String("part\0hidden")]:
        rejected = False
        try:
            var invalid = FileLock(bad)
        except e:
            rejected = "invalid path" in String(e)
        assert_true(rejected)
    var reader = FileLock(path, timeout=0, mode=.shared)
    var second_reader = FileLock(path, timeout=0, mode=.shared)
    assert_equal(reader.mode(), LockMode.shared)
    assert_true(try_acquire(reader))
    assert_true(try_acquire(second_reader))
    assert_true(not try_acquire(rival))
    reader.release()
    assert_true(not try_acquire(rival))
    second_reader.release()
    assert_true(try_acquire(rival))
    rival.release()
    rejected = False
    try:
        var invalid = FileLock(path, mode=LockMode(3))
    except e:
        rejected = "Invalid file lock mode" in String(e)
    assert_true(rejected)
    print(
        "PASS: move-only ownership, reentrancy, scoped"
        " errors/return/continue/break, and input rejection"
    )
